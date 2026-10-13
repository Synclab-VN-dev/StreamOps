import { Theme } from './settings/types';
import { D4PlannerCompactBuildHUD } from './components/generated/D4PlannerCompactBuildHUD';

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
      <D4PlannerCompactBuildHUD />
    </>
  ); // %EXPORT_STATEMENT%
}

export default App;
