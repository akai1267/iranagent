import { useState } from 'react'

import About from './components/about/About'
import IntelSummaryPane from './components/gtm/IntelSummaryPane'
import ResearchWorkspacePane from './components/gtm/ResearchWorkspacePane'
import Header from './components/layout/Header'
import TabNav from './components/layout/TabNav'
import { useGtmIntel } from './hooks/useGtmIntel'

export default function App() {
  const [activeTab, setActiveTab] = useState('intel')
  const { snapshot, loading, error } = useGtmIntel()

  return (
    <div className="app-shell">
      <Header />
      <main className="main-shell">
        <TabNav activeTab={activeTab} onChange={setActiveTab} />
        <section className="content-shell">
          {activeTab === 'intel' ? (
            <div className="main-split intel-shell">
              <IntelSummaryPane snapshot={snapshot} loading={loading} error={error} />
              <ResearchWorkspacePane snapshot={snapshot} loading={loading} error={error} />
            </div>
          ) : null}
          {activeTab === 'about' ? <About /> : null}
        </section>
      </main>
    </div>
  )
}
