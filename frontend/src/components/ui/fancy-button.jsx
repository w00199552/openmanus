import { cn } from "@/lib/utils";

/**
 * FancyButton — a CTA button with the devrajchatribin.com "fill up" hover.
 *
 * Anatomy (matches devraj's `.btn__outline`):
 *   <button overflow-hidden relative>
 *     <span class="ripple" />        ← colored slab, parked below the button
 *                                     (top: 100%), slides to top:0 on hover
 *     <span overflow-hidden>          ← clip mask for the rolling text
 *       <span class="layer-a">Label</span>   ← in place, slides up on hover
 *       <span class="layer-b">Label</span>   ← hidden below, slides in on hover
 *     </span>
 *   </button>
 *
 * Hover choreography (all on cubic-bezier(0.16,1,0.3,1)):
 *   1. ripple slab rises from bottom → fills the button
 *   2. text layer A slides up & out
 *   3. text layer B (in the contrast color) rolls in from below
 *
 * The whole handoff reads as the label being "refreshed" while the button
 * fills with color. Subtle, premium, restrained.
 *
 * The ripple is a plain rectangle (no top rounding): when it rises to fill,
 * the button's own `rounded-3xl + overflow-hidden` clips it into a perfect
 * rounded slab with no corner gaps. A rounded-top ripple would cave in at
 * the button's top edge and leave the center unfilled.
 *
 * Restraint: the button sits neutral (white hairline outline) by default.
 * The accent color only appears on hover as the fill — so the lime stays
 * scarce and meaningful.
 *
 * @param {object} props
 * @param {"accent"|"light"} [variant="accent"]  fill color on hover
 * @param {React.ReactNode} children  label (rendered twice for the roll)
 * @param {string} [className]        extra classes on the <button>
 */
export function FancyButton({
    children,
    variant = "accent",
    className,
    ...props
}) {
    const isAccent = variant === "accent";
    const rippleBg = isAccent ? "bg-accent" : "bg-foreground";
    // Text on the filled slab needs to read against the bright fill.
    const filledTextColor = isAccent
        ? "text-accent-foreground"
        : "text-background";

    return (
        <button
            type="button"
            className={cn(
                "group relative inline-flex shrink-0 items-center overflow-hidden rounded-3xl px-5 py-2",
                "font-sans text-[13px] font-semibold tracking-tight",
                "border text-foreground transition-[border-color] duration-300",
                // Neutral white hairline by default; tightens on hover so the
                // outline reads as "primed" right as the fill arrives.
                "border-foreground/25 hover:border-foreground/50",
                className
            )}
            {...props}
        >
            {/* Ripple slab — a plain rectangle parked below (top:100%).
                Slides up to top:0 on hover; the button clips it to rounded. */}
            <span
                className={cn(
                    "ripple pointer-events-none absolute inset-x-0 bottom-0 top-full transition-[top] duration-500",
                    "ease-[cubic-bezier(0.4,0,0,1)] group-hover:top-0",
                    rippleBg
                )}
            />
            {/* Text mask — the rolling label lives here. */}
            <span className="relative block overflow-hidden">
                {/* Layer A: default label, sits in place, slides up on hover */}
                <span className="block translate-y-0 transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-[120%]">
                    {children}
                </span>
                {/* Layer B: contrast label, hidden below, rolls in on hover.
                    Positioned absolutely so it overlays A's slot. */}
                <span
                    className={cn(
                        "absolute inset-0 translate-y-[120%] transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:translate-y-0",
                        filledTextColor
                    )}
                >
                    {children}
                </span>
            </span>
        </button>
    );
}
