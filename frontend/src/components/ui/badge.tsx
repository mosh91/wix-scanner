import * as React from "react";

import { cn } from "@/lib/utils";

type BadgeProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "secondary" | "outline";
};

const variantClasses: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default: "bg-primary text-primary-foreground",
  secondary: "bg-secondary text-secondary-foreground",
  outline: "border border-border text-foreground",
};

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  );
}
