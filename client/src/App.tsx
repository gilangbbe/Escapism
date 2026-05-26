import { ChatView } from "./components/ChatView";
import { Sidebar } from "./components/Sidebar";
import { resetSimulation, useGameSocket } from "./lib/socket";

export default function App() {
  const { events, world, connected } = useGameSocket();
  return (
    <div className="h-screen w-screen flex">
      <main className="flex-1 flex flex-col">
        <header className="px-6 py-3 border-b border-brass/30 bg-ink/50">
          <div className="text-xs uppercase tracking-widest text-brass">Group chat · The Black Vesper</div>
          <div className="text-lg">Mira & the Game Master</div>
        </header>
        <ChatView events={events} />
      </main>
      <Sidebar world={world} connected={connected} onReset={resetSimulation} />
    </div>
  );
}
