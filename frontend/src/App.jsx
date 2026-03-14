import { useEffect, useMemo, useState } from 'react'

import About from './components/about/About'
import Chat from './components/chat/Chat'
import CurrentPicture from './components/currentPicture/CurrentPicture'
import Feed from './components/feed/Feed'
import Header from './components/layout/Header'
import TabNav from './components/layout/TabNav'
import Ticker from './components/layout/Ticker'
import Observatory from './components/observatory/Observatory'
import Theories from './components/theories/Theories'
import { useCurrentPicture } from './hooks/useCurrentPicture'
import { useObservatory } from './hooks/useObservatory'
import { usePosts } from './hooks/usePosts'
import { useQuestions } from './hooks/useQuestions'
import { useTheories } from './hooks/useTheories'

const CHAT_PAUSED = true

export default function App() {
  const [activeTab, setActiveTab] = useState('feed')
  const [highlightPostId, setHighlightPostId] = useState(null)

  const { events, connected, agentStatus } = useObservatory()
  const { posts, newIds } = usePosts()
  const { questions } = useQuestions()
  const { content, updatedAt, justUpdated } = useTheories()
  const { snapshot, loading: currentPictureLoading, error: currentPictureError } = useCurrentPicture()

  const criticalEvent = useMemo(
    () =>
      events.find(
        (event) =>
          event.event_type === 'interrupt' &&
          (String(event.significance || '').toLowerCase() === 'critical' ||
            String(event.summary || '').toLowerCase().includes('critical')),
      ),
    [events],
  )

  const [tickerDismissedAt, setTickerDismissedAt] = useState(null)

  useEffect(() => {
    if (!highlightPostId) {
      return
    }
    const timer = window.setTimeout(() => setHighlightPostId(null), 3000)
    return () => window.clearTimeout(timer)
  }, [highlightPostId])

  const showTicker = Boolean(
    criticalEvent && (!tickerDismissedAt || Date.parse(criticalEvent.timestamp || 0) > tickerDismissedAt),
  )

  return (
    <div className="app-shell">
      <Header connected={connected} />
      <Ticker
        show={showTicker}
        headline={criticalEvent?.summary}
        onClose={() => setTickerDismissedAt(Date.now())}
      />

      <main className="main-split">
        <section className="left-pane">
          <TabNav activeTab={activeTab} onChange={setActiveTab} />
          <div className="left-content">
            {activeTab === 'feed' ? (
              <Feed posts={posts} newIds={newIds} questions={questions} highlightPostId={highlightPostId} />
            ) : null}

            {activeTab === 'theories' ? (
              <Theories content={content} updatedAt={updatedAt} justUpdated={justUpdated} />
            ) : null}

            {activeTab === 'current-picture' ? (
              <CurrentPicture
                snapshot={snapshot}
                loading={currentPictureLoading}
                error={currentPictureError}
              />
            ) : null}

            {activeTab === 'chat' ? (
              <Chat
                paused={CHAT_PAUSED}
                onCitation={(postId) => {
                  setActiveTab('feed')
                  setHighlightPostId(postId)
                }}
              />
            ) : null}

            {activeTab === 'about' ? <About /> : null}
          </div>
        </section>

        <aside className="right-pane">
          <Observatory events={events} connected={connected} agentStatus={agentStatus} />
        </aside>
      </main>
    </div>
  )
}
