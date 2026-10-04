import React from "react";
import { Link, useRouteError } from "react-router-dom";

interface RouteError {
    status?: number;
    statusText?: string;
    message?: string;
}

export default function ErrorPage() {
    const error = useRouteError() as RouteError;
    console.error(error);
    const notFound = error?.status === 404;

    return (
        <main className="flex h-full items-center justify-center bg-white px-6 dark:bg-zinc-950">
            <div className="text-center">
                <p className="text-sm font-semibold text-indigo-600">{notFound ? "404" : "Error"}</p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                    {notFound ? "Page not found" : "Something went wrong"}
                </h1>
                <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
                    {notFound ? "This page doesn't exist." : error?.statusText || error?.message}
                </p>
                <Link
                    to="/"
                    className="mt-6 inline-flex rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-500"
                >
                    Back to cudAI
                </Link>
            </div>
        </main>
    );
}
