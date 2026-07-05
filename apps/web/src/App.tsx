import { useState } from "react";

import { LeaderboardView } from "./views/LeaderboardView";
import { NewRunView } from "./views/NewRunView";
import { TasksView } from "./views/TasksView";

const VIEWS = ["Tasks", "New run", "Leaderboard"] as const;
type View = (typeof VIEWS)[number];

export function App() {
  const [view, setView] = useState<View>("Tasks");
  return (
    <main>
      <h1>Agent Arena</h1>
      <nav aria-label="Views">
        {VIEWS.map((name) => (
          <button key={name} aria-current={view === name} onClick={() => setView(name)}>
            {name}
          </button>
        ))}
      </nav>
      {view === "Tasks" && <TasksView />}
      {view === "New run" && <NewRunView />}
      {view === "Leaderboard" && <LeaderboardView />}
    </main>
  );
}
