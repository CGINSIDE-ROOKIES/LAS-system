"use client";

import type { ComponentProps } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

type NavLinkCompatProps = ComponentProps<typeof Link> & {
  className?: string;
  activeClassName?: string;
  pendingClassName?: string;
};

function normalizeHref(href: ComponentProps<typeof Link>["href"]) {
  return typeof href === "string" ? href : href.pathname ?? "";
}

function NavLink({ className, activeClassName, href, ...props }: NavLinkCompatProps) {
  const pathname = usePathname();
  const isActive = pathname === normalizeHref(href);

  return <Link href={href} className={cn(className, isActive && activeClassName)} {...props} />;
}

export { NavLink };
