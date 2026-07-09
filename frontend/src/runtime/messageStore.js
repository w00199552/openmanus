/**
 * messageStore — observable per-session message storage (mobx lives HERE only).
 *
 * Single responsibility: hold each session's Message[] and make it observable.
 * It does NOT interpret event semantics (that's eventReducer), talk to the
 * network, or know about React. mobx is confined to this one module so the
 * rest of the runtime stays free of reactivity concerns.
 *
 * Why a dedicated store class (vs. a plain object on the runtime): isolating
 * storage means a future change to how messages are held (pagination, virtual
 * lists, eviction of old sessions) touches ONLY this file.
 *
 * @module runtime/messageStore
 */

import {makeAutoObservable} from "mobx";

import {reduceEvent} from "./eventReducer.js";

export class MessageStore {
  /** @type {Record<string, import('./eventReducer').Message[]>} session_id → messages */
  messagesBySession = {};
  /** @type {Record<string, boolean>} session_id → history-loaded flag */
  loadedBySession = {};

  constructor() {
    makeAutoObservable(this);
  }

  /**
   * Apply one event to the session it belongs to, via the pure reducer.
   * The reducer returns a fresh immutable array; assigning it to the observable
   * map key is what mobx observes (reliable under React 19, unlike in-place
   * nested writes).
   */
  applyEvent(sessionId, event) {
    const cur = this.messagesBySession[sessionId] || [];
    this.messagesBySession[sessionId] = reduceEvent(cur, event);
  }

  /** Insert a fully-formed message (e.g. optimistic user bubble) at the end. */
  appendMessage(sessionId, message) {
    const cur = this.messagesBySession[sessionId] || [];
    this.messagesBySession[sessionId] = [...cur, message];
  }

  /** Messages for a session (empty array if none yet — always a stable ref). */
  get(sessionId) {
    return this.messagesBySession[sessionId] || [];
  }

  /** Replace a session's messages wholesale (history load). Marks it loaded. */
  set(sessionId, messages) {
    this.messagesBySession[sessionId] = Array.isArray(messages) ? messages : [];
    this.loadedBySession[sessionId] = true;
  }

  /** Has this session's history been loaded already? */
  isLoaded(sessionId) {
    return !!this.loadedBySession[sessionId];
  }

  /** Clear a session's messages + loaded flag (e.g. on reset). */
  clear(sessionId) {
    this.messagesBySession[sessionId] = [];
    this.loadedBySession[sessionId] = false;
  }

  /** Forget a session entirely (drops its entry from the maps). */
  forget(sessionId) {
    delete this.messagesBySession[sessionId];
    delete this.loadedBySession[sessionId];
  }
}
