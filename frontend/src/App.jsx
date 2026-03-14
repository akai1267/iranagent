import { useState } from 'react'

import About from './components/about/About'
import CurrentPicture from './components/currentPicture/CurrentPicture'
import Header from './components/layout/Header'
import TabNav from './components/layout/TabNav'
import { useCurrentPicture } from './hooks/useCurrentPicture'

export default function App() {
  const [activeTab, setActiveTab] = useState('current-picture')
  const { snapshot, loading: currentPictureLoading, error: currentPictureError } = useCurrentPicture()

  return (
    <div className="app-shell">
      <Header />
      <main className="main-shell">
        <TabNav activeTab={activeTab} onChange={setActiveTab} />
        <section className="content-shell">
          {activeTab === 'current-picture' ? (
            <CurrentPicture
              snapshot={snapshot}
              loading={currentPictureLoading}
              error={currentPictureError}
            />
          ) : null}
          {activeTab === 'about' ? <About /> : null}
        </section>
      </main>
    </div>
  )
}
