import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
import json

import yaml

from shared.base_agent import BaseAgent
from shared.schemas import AgentMessage, Signal


class OrchestratorAgent(BaseAgent):
    def __init__(self, redis_url: str, groq_key: str):
        resources_path = "/config/resources.yaml" if Path("/config/resources.yaml").exists() else "config/resources.yaml"
        super().__init__("orchestrator", redis_url, groq_key, resources_path=resources_path)

        self.researcher_state = "idle"
        self.researcher_focus = None
        self.researcher_publish_gate: dict = {}
        self.queue: asyncio.PriorityQueue[tuple[int, int, dict]] = asyncio.PriorityQueue()
        self._queue_seq = 0
        default_mode = os.environ.get("DEFAULT_MODE", "full").strip().lower()
        self.base_mode = default_mode if default_mode in {"full", "light", "minimal"} else "full"
        self.last_mode = self.base_mode
        self.mode_observe_interval_sec = 600
        self.mode_state_key = "mode_last_observed"
        self.mode_state_ts_key = "mode_last_observed_at"
        self.suppressed_medium_state_key = "suppressed_medium_signals"
        self.suppressed_medium_last_state_key = "suppressed_medium_last_at"
        self.suppress_observe_throttle_sec = self._env_int("ORCH_SUPPRESS_OBSERVE_THROTTLE_SEC", 300, minimum=30)

        resources = yaml.safe_load(Path(resources_path).read_text(encoding="utf-8"))
        raw_thresholds = resources.get("mode_thresholds", {"light_mode": 0.8, "minimal_mode": 0.95})
        light_default = float(raw_thresholds.get("light_mode", 0.8))
        minimal_default = float(raw_thresholds.get("minimal_mode", 0.95))
        light_mode = self._env_float("ORCH_LIGHT_MODE_THRESHOLD", light_default, minimum=0.1, maximum=0.98)
        minimal_mode = self._env_float("ORCH_MINIMAL_MODE_THRESHOLD", minimal_default, minimum=0.2, maximum=0.999)
        if minimal_mode <= light_mode:
            minimal_mode = min(0.999, light_mode + 0.05)
        self.mode_thresholds = {"light_mode": light_mode, "minimal_mode": minimal_mode}

    async def start(self) -> None:
        await asyncio.gather(super().start(), self.queue_processor(), self.mode_monitor())

    def current_mode(self) -> str:
        usage = max(self.rate_limiter.usage_fraction("standard"), self.rate_limiter.usage_fraction("deep"))
        if usage >= float(self.mode_thresholds.get("minimal_mode", 0.95)):
            computed = "minimal"
        elif usage >= float(self.mode_thresholds.get("light_mode", 0.8)):
            computed = "light"
        else:
            computed = "full"

        rank = {"full": 0, "light": 1, "minimal": 2}
        if rank[computed] < rank[self.base_mode]:
            return self.base_mode
        return computed

    async def mode_monitor(self) -> None:
        persisted = await self.get_agent_state(self.mode_state_key)
        if persisted in {"full", "light", "minimal"}:
            self.last_mode = persisted

        while True:
            mode = self.current_mode()
            if mode != self.last_mode:
                self.last_mode = mode
                for agent in ["monitor", "researcher"]:
                    await self.publish(agent, "resource_update", {"mode": mode})
                if await self._should_emit_mode_observe(mode):
                    await self.observe("decide", f"Mode -> {mode.upper()}")
            await asyncio.sleep(15)

    async def _should_emit_mode_observe(self, mode: str) -> bool:
        now = datetime.now(timezone.utc)
        last_mode = await self.get_agent_state(self.mode_state_key, default="")
        last_ts_raw = await self.get_agent_state(self.mode_state_ts_key, default="")

        should_emit = True
        if last_mode == mode and last_ts_raw:
            try:
                parsed = datetime.fromisoformat(last_ts_raw)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if (now - parsed).total_seconds() < self.mode_observe_interval_sec:
                    should_emit = False
            except ValueError:
                should_emit = True

        await self.set_agent_state(self.mode_state_key, mode)
        await self.set_agent_state(self.mode_state_ts_key, now.isoformat())
        return should_emit

    async def handle(self, message: AgentMessage) -> None:
        if message.type == "signal":
            await self.route_signal(message)
            return

        if message.type == "status":
            if message.from_agent != "researcher":
                return
            self.researcher_state = message.payload.get("state", "idle")
            self.researcher_focus = message.payload.get("focus")
            gate = message.payload.get("publish_gate")
            self.researcher_publish_gate = gate if isinstance(gate, dict) else {}
            return

        if message.type == "token_usage":
            model = message.payload.get("model")
            tokens = int(message.payload.get("tokens", 0))
            if model:
                self.rate_limiter.record_call(model, tokens)
            return

        if message.type == "query":
            await self.route_query(message)
            return

        if message.type == "reload_sources":
            await self.publish("monitor", "reload_sources", message.payload or {})
            await self.observe("decide", "Forwarded source reload request to monitor")
            return

    async def _record_suppressed_medium_signal(self, headline: str) -> None:
        raw = await self.get_agent_state(self.suppressed_medium_state_key, default="0")
        try:
            count = int(raw or 0)
        except ValueError:
            count = 0
        count += 1
        now_iso = datetime.now(timezone.utc).isoformat()
        await self.set_agent_state(self.suppressed_medium_state_key, str(count))
        await self.set_agent_state(self.suppressed_medium_last_state_key, now_iso)
        detail = json.dumps({"count": count, "headline": headline[:160]}, ensure_ascii=False)
        await self.observe_throttled(
            "suppressed_medium_signal",
            "decide",
            "suppressed_medium_signal: stale gate closed",
            detail=detail,
            throttle_seconds=self.suppress_observe_throttle_sec,
        )

    async def route_signal(self, message: AgentMessage) -> None:
        signal = Signal(**message.payload)
        mode = self.current_mode()
        publish_mode = str(self.researcher_publish_gate.get("publish_mode", "")).strip().lower()
        hard_blocked = publish_mode == "blocked"

        await self.observe(
            "decide",
            f"Signal [{signal.significance}] from {signal.source}: {signal.headline}",
            detail=signal.model_dump_json(),
            significance=signal.significance,
        )

        if mode == "minimal" and signal.significance != "critical":
            await self.observe("decide", "MINIMAL mode - skipping non-critical signal")
            return

        if signal.significance == "critical":
            await self.publish("researcher", "interrupt", message.payload, significance="critical")
            await self.observe("interrupt", "CRITICAL - interrupting researcher immediately", significance="critical")
            return

        if signal.significance == "high" and self.researcher_state == "idle":
            await self.publish("researcher", "interrupt", message.payload, significance="high")
            await self.observe("decide", "HIGH - routed directly to idle researcher")
            return

        if signal.significance == "low":
            await self.observe("decide", "LOW significance - noted only, no interrupt")
            return

        if hard_blocked and signal.significance == "medium":
            await self._record_suppressed_medium_signal(signal.headline)
            return

        priority = {"critical": 0, "high": 1, "medium": 2}.get(signal.significance, 3)
        self._queue_seq += 1
        await self.queue.put((priority, self._queue_seq, signal.model_dump(mode="json")))
        await self.observe("decide", f"[{signal.significance}] queued - researcher is {self.researcher_state}")

    async def queue_processor(self) -> None:
        while True:
            if self.researcher_state == "idle" and not self.queue.empty():
                _, _, payload = await self.queue.get()
                publish_mode = str(self.researcher_publish_gate.get("publish_mode", "")).strip().lower()
                significance = str(payload.get("significance", "medium")).strip().lower()
                if publish_mode == "blocked" and significance == "medium":
                    await self._record_suppressed_medium_signal(str(payload.get("headline", "")))
                    await asyncio.sleep(0)
                    continue
                await self.publish("researcher", "interrupt", payload, significance=payload.get("significance", "medium"))
                await self.observe("decide", "Queued signal routed to researcher")
            await asyncio.sleep(5)

    async def route_query(self, message: AgentMessage) -> None:
        urgent = bool(message.payload.get("urgent", False))
        if urgent:
            await self.publish("researcher", "interrupt", message.payload, significance="high")
        else:
            await self.publish("researcher", "query", message.payload, significance="low")

        await self.observe(
            "decide",
            f"Query routed (urgent={urgent}): {message.payload.get('question', '')[:80]}",
        )
