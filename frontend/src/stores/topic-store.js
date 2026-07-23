import { makeAutoObservable, runInAction } from "mobx";

import * as topicApi from "@/services/topic-service";

const LS_KEY = "openmanus.activeTopicId";

/**
 * The fixed topic id of the permanent "main" topic — the entry agent's home.
 * Always visible, never deleted. "New chat" resets its history.
 */
export const MAIN_TOPIC_ID = "main";

/**
 * TopicStore — owns the topic list (what the user sees in the left rail) and
 * the active topic id. Each topic maps to one task/conversation group.
 *
 * Topics come from GET /topics; each carries a `session_id` (the latest
 * session in that topic) but the frontend keys runs by topic_id now
 * (POST /topics/{topic_id}/messages), so session_id stays on the topic object
 * for places that still need it (e.g. the cd API) but isn't tracked as
 * top-level runtime state anymore.
 */
export class TopicStore {
    topics = [];
    activeTopicId = null;
    loading = false;
    error = null;
    unread = {};

    constructor() {
        makeAutoObservable(this);
        this.activeTopicId = localStorage.getItem(LS_KEY) || MAIN_TOPIC_ID;
    }

    /** The active topic object (or null if not loaded yet). */
    get active() {
        return this.topics.find((t) => t.id === this.activeTopicId) || null;
    }

    /** Topics sorted by last-activity, main pinned to top. */
    get sortedTopics() {
        return [...this.topics].sort((a, b) => {
            const am = a.id === MAIN_TOPIC_ID ? 1 : 0;
            const bm = b.id === MAIN_TOPIC_ID ? 1 : 0;
            if (am !== bm) return bm - am;
            const ta = _ts(a.updated_at) || _ts(a.created_at) || 0;
            const tb = _ts(b.updated_at) || _ts(b.created_at) || 0;
            return tb - ta;
        });
    }

    /** The main topic (default entry, always shown). */
    get mainTopic() {
        return this.sortedTopics.filter((t) => t.id === MAIN_TOPIC_ID);
    }

    /** Non-main topics (dispatched tasks). */
    get taskTopics() {
        return this.sortedTopics.filter((t) => t.id !== MAIN_TOPIC_ID);
    }

    /** Load the topic list from the backend. */
    async load() {
        this.loading = true;
        this.error = null;
        try {
            const data = await topicApi.listTopics();
            runInAction(() => {
                this.topics = Array.isArray(data) ? data : [];
                this.loading = false;
                if (
                    this.activeTopicId &&
                    this.activeTopicId !== MAIN_TOPIC_ID &&
                    !this.topics.some((t) => t.id === this.activeTopicId)
                ) {
                    this._setActive(MAIN_TOPIC_ID);
                }
            });
            return this.topics;
        } catch (e) {
            runInAction(() => {
                this.error = e.message || String(e);
                this.loading = false;
            });
            return [];
        }
    }

    /** Select a topic (updates activeTopicId + persists to localStorage). */
    select(topicId) {
        this._setActive(topicId);
    }

    _setActive(topicId) {
        this.activeTopicId = topicId;
        localStorage.setItem(LS_KEY, topicId);
    }

    /** Bump a topic's activity (preview/unread) — called by runtime on new messages. */
    bumpActivity(topicId, { preview, speaker, unread } = {}) {
        const t = this.topics.find((x) => x.id === topicId);
        if (!t) return;
        if (preview !== undefined) t.preview = preview;
        if (unread !== undefined) this.unread[topicId] = unread;
    }

    /** Mark a topic's status (running/active/error). */
    markStatus(topicId, status) {
        const t = this.topics.find((x) => x.id === topicId);
        if (t) t.status = status;
    }

    /** Mark a topic as currently running (spinner in list). */
    markRunning(topicId) {
        this.markStatus(topicId, "running");
    }

    /** Unread count for a topic (0 if none / not tracked). */
    unreadCount(topicId) {
        return this.unread[topicId] || 0;
    }
}

function _ts(s) {
    if (!s) return 0;
    return Date.parse(String(s).replace(" ", "T")) || 0;
}
