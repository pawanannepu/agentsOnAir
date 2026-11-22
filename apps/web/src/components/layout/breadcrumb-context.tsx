"use client";

import * as React from "react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbContextType {
  breadcrumbs: BreadcrumbItem[];
  setBreadcrumbs: React.Dispatch<React.SetStateAction<BreadcrumbItem[]>>;
}

const BreadcrumbContext = React.createContext<BreadcrumbContextType>({
  breadcrumbs: [],
  setBreadcrumbs: () => {},
});

export function BreadcrumbProvider({
  children,
  initialBreadcrumbs = [],
}: {
  children: React.ReactNode;
  initialBreadcrumbs?: BreadcrumbItem[];
}) {
  const [breadcrumbs, setBreadcrumbs] =
    React.useState<BreadcrumbItem[]>(initialBreadcrumbs);

  return (
    <BreadcrumbContext.Provider value={{ breadcrumbs, setBreadcrumbs }}>
      {children}
    </BreadcrumbContext.Provider>
  );
}

export function useBreadcrumbs(items?: BreadcrumbItem[]) {
  const { breadcrumbs, setBreadcrumbs } = React.useContext(BreadcrumbContext);

  const serialized = JSON.stringify(items || []);

  React.useEffect(() => {
    const parsedItems = JSON.parse(serialized) as BreadcrumbItem[];
    if (parsedItems.length > 0) {
      setBreadcrumbs((prev) => {
        if (
          prev.length === parsedItems.length &&
          prev.every(
            (p, idx) =>
              p.label === parsedItems[idx]?.label &&
              p.href === parsedItems[idx]?.href
          )
        ) {
          return prev;
        }
        return parsedItems;
      });
    }
  }, [serialized, setBreadcrumbs]);

  return { breadcrumbs, setBreadcrumbs };
}
