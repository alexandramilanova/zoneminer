import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import "@fontsource-variable/inter";
import "./theme.css";
import Layout from "./components/Layout";
import { AppStateProvider } from "./state";
import Workspace from "./pages/Workspace";
import Overview from "./pages/Overview";
import Replay from "./pages/Replay";
import Trends from "./pages/Trends";
import FlowPatterns from "./pages/FlowPatterns";
import Dependencies from "./pages/Dependencies";
import Prediction from "./pages/Prediction";
import Metrics from "./pages/Metrics";

const router = createHashRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Workspace /> },
      { path: "/overview", element: <Overview /> },
      { path: "/replay", element: <Replay /> },
      { path: "/trends", element: <Trends /> },
      { path: "/flow", element: <FlowPatterns /> },
      { path: "/dependencies", element: <Dependencies /> },
      { path: "/prediction", element: <Prediction /> },
      { path: "/metrics", element: <Metrics /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppStateProvider>
      <RouterProvider router={router} />
    </AppStateProvider>
  </React.StrictMode>,
);
