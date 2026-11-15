import AboutYouSection from '../sections/AboutYouSection.tsx'
import ResumeSection from '../sections/ResumeSection.tsx'
import AiSection from '../sections/AiSection.tsx'
import SearchSection from '../sections/SearchSection.tsx'
import WatchlistSection from '../sections/WatchlistSection.tsx'
import ImportSection from '../sections/ImportSection.tsx'
import ScheduleSection from '../sections/ScheduleSection.tsx'
import LimitsSection from '../sections/LimitsSection.tsx'
import DocumentsSection from '../sections/DocumentsSection.tsx'
import TrackingSection from '../sections/TrackingSection.tsx'
import JobFieldsSection from '../sections/JobFieldsSection.tsx'

// Sections are listed in wizard order.
export default function Settings() {
  return (
    <section>
      <h1>Settings</h1>
      <AiSection mode="settings" />
      <AboutYouSection mode="settings" />
      <ResumeSection mode="settings" />
      <SearchSection mode="settings" />
      <WatchlistSection mode="settings" />
      <ImportSection mode="settings" />
      <ScheduleSection mode="settings" />
      <LimitsSection mode="settings" />
      <DocumentsSection mode="settings" />
      <TrackingSection mode="settings" />
      <JobFieldsSection />
    </section>
  )
}
