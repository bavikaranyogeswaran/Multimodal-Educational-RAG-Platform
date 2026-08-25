/**
 * What this application needs from a sign-in service, and nothing more.
 *
 * Stated as an interface so the screens, the session store and the API client depend on
 * these five operations rather than on the vendor's SDK. That keeps the SDK out of every
 * test that wants to assert what happens when a token expires or a password is wrong,
 * and it makes the surface small enough to read: everything the rest of the application
 * can do about identity is on this page.
 */

/** Who is signed in, and the credential that proves it to the API. */
export interface Session {
  /**
   * Read fresh each time it is needed rather than stored. Access tokens are short-lived
   * and refreshed in the background, so one captured at sign-in is stale within the hour.
   */
  accessToken: string;
  userId: string;
  email: string | null;
}

export interface Credentials {
  email: string;
  password: string;
}

/**
 * Whether signing up produced a usable session.
 *
 * A project that verifies email addresses accepts the registration and returns no
 * session, and treating that as success sends someone to a signed-out application that
 * looks broken. Naming the two outcomes forces the screen to tell them apart.
 */
export type SignUpOutcome = 'signed-in' | 'confirmation-required';

/** A refusal from the sign-in service, carrying the message it gave. */
export class AuthenticationFailure extends Error {
  override readonly name = 'AuthenticationFailure';

  constructor(message: string) {
    super(message);
  }
}

/**
 * Written as properties holding functions rather than as methods, because that is what
 * they are: an implementation returns an object of closures, and callers pull them off it
 * and pass them around. Method syntax would type them as bound to a receiver that does
 * not exist.
 */
export interface AuthGateway {
  /**
   * The session as it stands now, refreshing the token first if it is close to expiring.
   * Returns null when nobody is signed in.
   */
  currentSession: () => Promise<Session | null>;

  /**
   * Called whenever the session changes: signing in, signing out, and each background
   * token refresh. Returns the function that stops the subscription.
   */
  onChange: (listener: (session: Session | null) => void) => () => void;

  signIn: (credentials: Credentials) => Promise<Session>;
  signUp: (credentials: Credentials) => Promise<SignUpOutcome>;
  signOut: () => Promise<void>;
}
