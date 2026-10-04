import * as ReactDOM from "react-dom/client";
import { Navigate, createHashRouter, RouterProvider, useParams } from "react-router-dom";

import App from "./App";
import ErrorPage from "../routes/error-page";
import Homepage from "../components/Homepage/Homepage";
import RecordingsPage from "../components/Recordings/RecordingsPage";
import ReviewPage from "../components/Review/ReviewPage";
import SettingsPage from "../components/Settings/SettingsPage";
import { MainProvider } from "../context/MainContext";
import "./globals.css";

// Old links used /tasks/<id>.
function LegacyTaskRedirect() {
    const { recordingId } = useParams();
    return <Navigate to={`/recordings/${recordingId}`} replace />;
}

const router = createHashRouter([
    {
        path: "/",
        element: <App />,
        errorElement: <ErrorPage />,
        children: [
            { index: true, element: <Homepage /> },
            { path: "recordings", element: <RecordingsPage /> },
            { path: "recordings/:recordingId", element: <ReviewPage /> },
            { path: "tasks/:recordingId", element: <LegacyTaskRedirect /> },
            { path: "settings", element: <SettingsPage /> },
        ],
    },
]);

ReactDOM.createRoot(document.querySelector("#root")!).render(
    // StrictMode is off: it double-invokes effects, which double-registers
    // global shortcut listeners in development.
    <MainProvider>
        <RouterProvider router={router} />
    </MainProvider>
);
