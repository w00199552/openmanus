import {clsx} from "clsx"
import {twMerge} from "tailwind-merge"

/** Merge tailwind classes with conditional logic (shadcn standard helper). */
export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
