import React, { useState } from "react";
import { api } from "../../lib/api";

// DRAFT terms: have them reviewed by counsel before release. Bump
// CONSENT_VERSION in api/core/consent.py whenever this text changes materially
// so every contributor is asked to accept again.
const CONTACT_EMAIL = ""; // TODO: set a support/privacy contact before release

interface TermsAndConsentProps {
    version: string;
    // True when reviewing already-accepted terms from Settings (read-only).
    accepted: boolean;
    onAccepted: () => void;
    onClose?: () => void;
}


const TermsAndConsent: React.FC<TermsAndConsentProps> = ({
    version,
    accepted,
    onAccepted,
    onClose,
}) => {
    const [isChecked, setIsChecked] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const accept = async () => {
        setSaving(true);
        setError(null);
        try {
            await api.post("/api/consent", { accepted: true, version });
            onAccepted();
        } catch (e: any) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="bg-white dark:bg-gray-900 w-full overflow-y-auto px-6 py-16 lg:px-8">
            <div className="mx-auto max-w-3xl text-base leading-7 text-gray-700 dark:text-gray-300">
                <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
                    Recording consent
                </h1>
                <p className="mt-2 text-sm text-gray-500">Version {version}</p>
                {accepted ? (
                    <p className="mt-4 rounded-md bg-green-50 p-3 text-sm text-green-800">
                        You accepted these terms.
                    </p>
                ) : (
                    <p className="mt-4 rounded-md bg-indigo-50 p-3 text-sm text-indigo-800">
                        You must accept these terms to use cudAI.
                    </p>
                )}

                <div className="mt-8 space-y-6 rounded-lg bg-gray-50 dark:bg-gray-800 p-6 text-sm">
                    <section>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            What cudAI records
                        </h2>
                        <p className="mt-2">
                            Only while you have started a recording and it is not
                            paused, cudAI captures:
                        </p>
                        <ul className="mt-2 list-disc pl-5 space-y-1">
                            <li>a video of each of your displays;</li>
                            <li>
                                mouse movements, clicks and scrolls, and keyboard
                                input, including the text you type and the
                                shortcuts you use;
                            </li>
                            <li>
                                the name of the active application, the title
                                and position of its window and, in web browsers,
                                the address of the page;
                            </li>
                            <li>
                                accessibility information about the on-screen
                                elements you click (such as a button's label);
                            </li>
                            <li>
                                device details: computer model, operating system,
                                display layout, language, keyboard layout and
                                time zone.
                            </li>
                        </ul>
                        <p className="mt-2">
                            cudAI does not record audio or your camera, and records
                            nothing while paused or stopped. Input you give to the
                            cudAI app itself is excluded.
                        </p>
                    </section>

                    <section>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            Protect sensitive information
                        </h2>
                        <p className="mt-2">
                            cudAI automatically removes passwords, access tokens and
                            keys, email addresses, phone numbers, card and bank
                            account numbers, government ID numbers (such as Aadhaar,
                            PAN, SSN and passport numbers) and IP/MAC addresses from
                            the recorded text: typing, window titles, page
                            addresses and on-screen element labels. They are
                            replaced with labels such as [EMAIL_ADDRESS].
                        </p>
                        <p className="mt-2">
                            The screen video is not redacted. Everything visible on
                            your screen is captured, so pause before entering
                            passwords, payment details, or personal or confidential
                            information, and do not record other people's data
                            without permission.
                        </p>
                    </section>

                    <section>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            Where recordings are kept
                        </h2>
                        <p className="mt-2">
                            Recordings are uploaded automatically to cudAI's secure
                            cloud storage while they are being made, in 10-second
                            parts, and a copy is kept on this computer. Recordings
                            cannot be deleted from the app once made. You can review
                            them and edit their task descriptions and annotations;
                            your edits are uploaded too.
                        </p>
                        <p className="mt-2">
                            Recordings made under earlier versions of these terms
                            stay on this computer and are not uploaded.
                        </p>
                    </section>

                    <section>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            How recordings are used
                        </h2>
                        <p className="mt-2">
                            Recordings may be reviewed,
                            annotated and combined into datasets, and those
                            datasets may be licensed or sold to third parties,
                            including AI companies and research labs, to train and
                            evaluate AI systems.
                        </p>
                    </section>

                    <section>
                        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                            Your choices
                        </h2>
                        <p className="mt-2">
                            Accepting these terms is required to use cudAI and,
                            once accepted, cannot be withdrawn in the app. You
                            decide when to start, pause and stop recording.
                            {CONTACT_EMAIL &&
                                ` For questions about data already collected, contact ${CONTACT_EMAIL}.`}
                        </p>
                    </section>
                </div>

                {!accepted && (
                    <label className="mt-8 flex items-start gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
                        <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={(e) => setIsChecked(e.target.checked)}
                            className="mt-1 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-600"
                        />
                        I have read and understood what cudAI records and how
                        recordings are used, and I agree to these terms.
                    </label>
                )}

                {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

                <div className="mt-6 flex gap-4">
                    {!accepted && (
                        <>
                            <button
                                onClick={accept}
                                disabled={!isChecked || saving}
                                className="rounded-md bg-indigo-600 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                Agree and continue
                            </button>
                            <button
                                onClick={() =>
                                    window.electron.ipcRenderer.sendMessage("quit-app")
                                }
                                className="rounded-md bg-white px-3.5 py-2.5 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50"
                            >
                                Quit cudAI
                            </button>
                        </>
                    )}
                    {onClose && (
                        <button
                            onClick={onClose}
                            className="rounded-md bg-indigo-600 px-3.5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500"
                        >
                            Close
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default TermsAndConsent;
