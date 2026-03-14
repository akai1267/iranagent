const TABS = [
  { id: 'current-picture', label: 'CURRENT PICTURE' },
  { id: 'about', label: 'ABOUT' },
]

export default function TabNav({ activeTab, onChange }) {
  return (
    <nav className="tab-nav" aria-label="Primary navigation">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  )
}
