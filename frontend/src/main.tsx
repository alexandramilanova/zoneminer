import React, { lazy } from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import "@fontsource-variable/inter";
import "./theme.css";
import Layout from "./components/Layout";
import { AppStateProvider } from "./state";
const Workspace = lazy(() => import("./pages/Workspace"));
const Overview = lazy(() => import("./pages/Overview"));
const Replay = lazy(() => import("./pages/Replay"));
const Trends = lazy(() => import("./pages/Trends"));
const FlowPatterns = lazy(() => import("./pages/FlowPatterns"));
const Dependencies = lazy(() => import("./pages/Dependencies"));
const Prediction = lazy(() => import("./pages/Prediction"));
const Metrics = lazy(() => import("./pages/Metrics"));

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
