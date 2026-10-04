import * as React from "react";
import { Outlet } from "react-router-dom";

import Sidebar from "../components/Sidebar";
import TermsAndConsent from "../components/prerequisite/Terms";
import { Spinner } from "../components/ui";
import { api } from "../lib/api";

interface ConsentState {
  current_version: string;
  accepted: boolean;
}

export default function App() {
  const [consent, setConsent] = React.useState<ConsentState | null>(null);

  const loadConsent = React.useCallback(async () => {
    try {
      setConsent(await api.get<ConsentState>("/api/consent"));
    } catch {
      // Backend still starting.
      setTimeout(loadConsent, 1000);
    }
  }, []);

  React.useEffect(() => {
    loadConsent();
  }, [loadConsent]);

  if (consent === null) {
    return (
      <div className="flex h-full items-center justify-center bg-white text-zinc-400 dark:bg-zinc-950">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  if (!consent.accepted) {
    return (
      <div className="h-full overflow-y-auto bg-white dark:bg-zinc-950">
        <TermsAndConsent
          version={consent.current_version}
          accepted={false}
          onAccepted={loadConsent}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full w-full bg-white text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
