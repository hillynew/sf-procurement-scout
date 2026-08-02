import { lazy, Suspense } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import AppShell from "./components/AppShell";
import { Spinner } from "./components/ui";
import AllBids from "./screens/AllBids";
import CalendarScreen from "./screens/Calendar";
import Pipeline from "./screens/Pipeline";
import Workroom from "./screens/Workroom";
import Watchlists from "./screens/Watchlists";
import Sources from "./screens/Sources";
import SettingsScreen from "./screens/Settings";

// Recharts is the heaviest dependency — keep it out of the main chunk.
const Dashboard = lazy(() => import("./screens/Dashboard"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: true },
  },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
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
      { path: "bids/:id", element: <Workroom /> },
      { path: "calendar", element: <CalendarScreen /> },
      { path: "pipeline", element: <Pipeline /> },
      { path: "watchlists", element: <Watchlists /> },
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
