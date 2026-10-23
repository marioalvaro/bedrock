import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";

import { companiesQueryOptions, companyErrorMessage } from "@/api/companies";
import { peerSuggestionsQueryOptions, useCreateCompsSet, useUpdateCompsSet } from "@/api/context";
import type { CompsSetOut, PeerSuggestionOut } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const SELECT = "border-input h-8 rounded-lg border bg-transparent px-2 text-sm";

// The SIC digits a match level shares with the company: "DE · major group 35".
const MATCH_DIGITS: Record<PeerSuggestionOut["match"], number> = {
  industry: 4,
  "industry group": 3,
  "major group": 2,
};

const memberTickers = (set: CompsSetOut) => set.members.map((member) => member.ticker);

// What the name form starts from: a new, empty set or a rename of one.
export type SetNameMode = { type: "new" } | { type: "rename"; set: CompsSetOut };

interface SetNameFormProps {
  ticker: string;
  mode: SetNameMode;
  // Called after a save with the saved set's id, or with null on Cancel.
  onDone: (id: number | null) => void;
}

/** Names a new comps set (no members yet) or renames one, keeping its members. */
export function SetNameForm({ ticker, mode, onDone }: SetNameFormProps) {
  const create = useCreateCompsSet(ticker);
  const update = useUpdateCompsSet(ticker);
  const [name, setName] = useState(mode.type === "rename" ? mode.set.name : "");
  const [error, setError] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (name.trim() === "") return setError("Enter a name");
    setError(null);
    const options = {
      onSuccess: (saved: CompsSetOut) => onDone(saved.id),
      onError: (e: Error) => setError(companyErrorMessage(e, "Could not save the comps set.")),
    };
    if (mode.type === "rename") {
      const body = { name: name.trim(), members: memberTickers(mode.set) };
      update.mutate({ id: mode.set.id, body }, options);
    } else {
      create.mutate({ name: name.trim(), members: [] }, options);
    }
  }

  return (
    <form onSubmit={submit} className="border-border space-y-2 border-b px-4 py-3" noValidate>
      <div className="max-w-sm space-y-1">
        <Label htmlFor="comps-set-name">Name</Label>
        <Input
          id="comps-set-name"
          value={name}
          maxLength={60}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={create.isPending || update.isPending}>
          Save
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => onDone(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

interface MemberEditorProps {
  ticker: string;
  set: CompsSetOut;
}

/**
 * The set's members as removable chips and an "Add peer" select of the followed companies, the
 * suggested ones first; Save members sends the whole list. Keyed by the set's stored members, so a
 * save or another set starts a fresh draft.
 */
export function MemberEditor({ ticker, set }: MemberEditorProps) {
  const update = useUpdateCompsSet(ticker);
  const { data: companies = [] } = useQuery(companiesQueryOptions);
  const { data: suggestions = [] } = useQuery(peerSuggestionsQueryOptions(ticker, set.id));
  const [members, setMembers] = useState(memberTickers(set));
  const [error, setError] = useState<string | null>(null);

  const names = new Map(companies.map((company) => [company.ticker, company.name]));
  for (const member of set.members) names.set(member.ticker, member.name);
  const taken = new Set([ticker, ...members]);
  const suggested = suggestions.filter((suggestion) => !taken.has(suggestion.ticker));
  const suggestedTickers = new Set(suggestions.map((suggestion) => suggestion.ticker));
  const others = companies.filter(
    (company) => !taken.has(company.ticker) && !suggestedTickers.has(company.ticker),
  );
  const dirty = members.join() !== memberTickers(set).join();

  function add(peer: string) {
    if (peer) setMembers([...members, peer].sort());
  }

  function save() {
    setError(null);
    update.mutate(
      { id: set.id, body: { name: set.name, members } },
      { onError: (e) => setError(companyErrorMessage(e, "Could not save the members.")) },
    );
  }

  return (
    <div className="border-border space-y-2 border-b px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted-foreground text-xs">Peers</span>
        {members.length === 0 && <span className="text-muted-foreground text-sm">none</span>}
        {members.map((member) => (
          <span
            key={member}
            title={names.get(member)}
            className="border-border inline-flex items-center gap-1 rounded-full border py-0.5 pr-1 pl-2 text-xs"
          >
            {member}
            <button
              type="button"
              aria-label={`Remove ${member}`}
              className="text-muted-foreground hover:text-foreground rounded-full"
              onClick={() => setMembers(members.filter((m) => m !== member))}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <select
          aria-label="Add peer"
          value=""
          onChange={(e) => add(e.target.value)}
          className={SELECT}
        >
          <option value="">Add peer…</option>
          {suggested.length > 0 && (
            <optgroup label="Suggested">
              {suggested.map((s) => (
                <option key={s.ticker} value={s.ticker}>
                  {`${s.ticker} · ${s.match} ${s.sic.slice(0, MATCH_DIGITS[s.match])}`}
                </option>
              ))}
            </optgroup>
          )}
          {others.length > 0 && (
            <optgroup label="Other followed">
              {others.map((company) => (
                <option key={company.ticker} value={company.ticker}>
                  {`${company.ticker} · ${company.name}`}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <Button size="sm" disabled={!dirty || update.isPending} onClick={save}>
          Save members
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
