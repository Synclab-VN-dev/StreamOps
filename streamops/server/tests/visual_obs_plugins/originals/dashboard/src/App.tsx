import { Theme } from './settings/types';
import { StreamOpsMobileDashboard } from './components/generated/StreamOpsMobileDashboard';

let theme: Theme = 'light';

function App() {
  function setTheme(theme: Theme) {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }

  setTheme(theme);

  return (
    <>
      <StreamOpsMobileDashboard />
    </>
  ); // %EXPORT_STATEMENT%
}

export default App;
