import { makeAutoObservable, runInAction } from "mobx";

import { listSkills } from "@/services/agentService";

/**
 * SkillStore — manages skill list from ~/.openmanus/skills/.
 * View → store → service.
 */
export class SkillStore {
    skills = [];
    loading = false;
    error = null;

    constructor() {
        makeAutoObservable(this);
    }

    async loadSkills() {
        this.loading = true;
        try {
            const data = await listSkills();
            runInAction(() => {
                this.skills = data;
                this.loading = false;
            });
        } catch (e) {
            runInAction(() => {
                this.error = e.message;
                this.loading = false;
            });
        }
    }
}
