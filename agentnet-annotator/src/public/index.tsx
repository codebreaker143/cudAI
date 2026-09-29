import * as ReactDOM from "react-dom/client";
import App from "./App";

import { createHashRouter, RouterProvider } from "react-router-dom";
import ErrorPage from "../routes/error-page";
import Page from "../components/Local/page";
import Homepage from "../components/Homepage/Homepage";
import "./globals.css";
import { MainProvider } from "../context/MainContext";
import Report from "../components/Report/Report";
import DisAgreePage from "../routes/disagree-page";

const router = createHashRouter([
    {
        path: "/",
        element: <App />,
        errorElement: <ErrorPage />,
        children: [
            {
                path: "/tasks/:recording_name",
                element: <Page />,
                loader: async ({ params }) => {
                    const res = await fetch(
                        `http://localhost:5328/api/recording/${params.recording_name}`
                    );
                    if (!res.ok) {
                        throw new Error("Failed to load task");
                    }
                    return {
                        recording_name: params.recording_name,
                        task_data: await res.json(),
                    };
                },
            },
            {
                path: "/",
                index: true,
                element: <Homepage />,
            },
            {
                path: "/report",
                element: <Report />,
            },
            {
                path: "/disagree",
                element: <DisAgreePage />,
            },
        ],
    },
]);

ReactDOM.createRoot(document.querySelector("#root")!).render(
    // <React.StrictMode>
    <MainProvider>
        <RouterProvider router={router} />
    </MainProvider>
    // </React.StrictMode>
    // In development mode, StrictMode causes component lifecycle methods (including the constructor, render method, and useEffect hook) to be invoked twice, and 'start-record' is also listened twice. Therefore, we comment it out.
);
