import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { unwrap } from "@/api/errors";
import { getCompaniesApiV1CompaniesGet } from "@/api/generated/sdk.gen";

export function Companies() {
  const {
    data: companies,
    isPending,
    isError,
  } = useQuery({
    queryKey: ["companies"],
    queryFn: () => unwrap(getCompaniesApiV1CompaniesGet()),
  });

  if (isPending) {
    return null;
  }

  if (isError) {
    return <p className="text-destructive p-4 text-sm">Could not load companies.</p>;
  }

  if (companies.length === 0) {
    return (
      <p className="text-muted-foreground p-4 text-sm">
        No companies yet. Adding companies arrives in M1.
      </p>
    );
  }

  return (
    <ul className="divide-border divide-y">
      {companies.map((company) => (
        <li key={company.id}>
          <Link to={`/c/${company.ticker}`} className="block p-2 hover:bg-muted">
            {company.ticker} — {company.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}
