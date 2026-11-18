import { strings } from "./strings";

export function App() {
  return (
    <main>
      {import.meta.env.DEV && <div role="note">{strings.app.devRibbon}</div>}
      <h1>{strings.app.title}</h1>
      <p>{strings.app.simulationLabel}</p>
    </main>
  );
}
