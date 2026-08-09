import { lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createBrowserRouter,
  Link,
  Navigate,
  RouterProvider,
  useRouteError,
} from "react-router-dom";
import { Toaster } from "sonner";
import AppShell from "./components/AppShell";
import { Spinner } from "./components/ui";
import AllBids from "./screens/AllBids";
import Pipeline from "./screens/Pipeline";
import Workroom from "./screens/Workroom";
import Watchlists from "./screens/Watchlists";
import Network from "./screens/Network";
import Sources from "./screens/Sources";
import SettingsScreen from "./screens/Settings";

// Recharts is the heaviest dependency — keep it out of the main chunk.
const Dashboard = lazy(() => import("./screens/Dashboard"));
import Awards from "./screens/Awards";

/** Friendly crash screen so a component error never white-pages the app. */
function RouteError() {
  const error = useRouteError();
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="card max-w-md p-6 text-center">
        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-danger-soft text-2xl">
          😵
        </div>
        <h1 className="text-lg font-bold">Something broke on this screen</h1>
        <p className="mt-2 break-words text-sm text-ink-soft">{message}</p>
        <div className="mt-4 flex justify-center gap-2">
          <button
            onClick={() => window.location.reload()}
            className="rounded-[10px] bg-accent px-4 py-2 text-sm font-bold text-white hover:bg-accent-deep"
          >
            Reload
          </button>
          <Link
            to="/"
            className="rounded-[10px] border border-line px-4 py-2 text-sm font-semibold text-ink-soft hover:border-accent hover:text-accent"
          >
            Go to dashboard
          </Link>
        </div>
      </div>
    </div>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true },
  },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={<div className="flex justify-center py-24"><Spinner size={26} /></div>}>
            <Dashboard />
          </Suspense>
        ),
      },
      { path: "bids", element: <AllBids /> },
      // The Calendar screen is gone; bookmarks land on the bid list instead
      // of the crash page.
      { path: "calendar", element: <Navigate to="/bids" replace /> },
      { path: "bids/:id", element: <Workroom /> },
      { path: "awards", element: <Awards /> },
      { path: "pipeline", element: <Pipeline /> },
      { path: "watchlists", element: <Watchlists /> },
      { path: "network", element: <Network /> },
      { path: "sources", element: <Sources /> },
      { path: "settings", element: <SettingsScreen /> },
    ],
  },
]);

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  );
}
