import { Theme } from './settings/types';
import { StreamOpsOBSPluginManager } from './components/generated/StreamOpsOBSPluginManager';

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
      <StreamOpsOBSPluginManager />
    </>
  ); // %EXPORT_STATEMENT%
}

export default App;
