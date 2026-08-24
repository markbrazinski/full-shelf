/** Environment contract for the Full Shelf operator UI.
 *
 * The data source is chosen at build time. `deterministic_replay` points the
 * client at the loopback replay harness and MUST render a visible
 * DETERMINISTIC TEST MODE indicator. It can never be selected in a deployed
 * environment: the replay harness binds only to 127.0.0.1 and ships in no
 * container image.
 */
export type DataSource = 'live' | 'deterministic_replay';

const rawSource = import.meta.env.VITE_DATA_SOURCE ?? 'live';

export const DATA_SOURCE: DataSource =
  rawSource === 'deterministic_replay' ? 'deterministic_replay' : 'live';

export const IS_REPLAY = DATA_SOURCE === 'deterministic_replay';

export const ENV = {
  DATA_SOURCE,
  IS_REPLAY,
  /** Orchestrator origin. The private plan ledger is never called from a browser. */
  ORCHESTRATOR_URL:
    import.meta.env.VITE_ORCHESTRATOR_URL ??
    (IS_REPLAY ? 'http://127.0.0.1:8787' : ''),
  /** Public by design; not a secret. */
  OPERATOR_OAUTH_CLIENT_ID: import.meta.env.VITE_OPERATOR_OAUTH_CLIENT_ID ?? '',
};
