import { NavLink } from "react-router";

import { useLogout } from "@/api/auth";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";

const navLinkClassName = ({ isActive }: { isActive: boolean }) =>
  isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground";

export function Header() {
  const logout = useLogout();

  return (
    <header className="border-border flex items-center gap-4 border-b px-4 py-2">
      <span className="text-sm font-medium">Bedrock</span>
      <nav className="flex gap-3 text-sm">
        <NavLink to="/" end className={navLinkClassName}>
          Companies
        </NavLink>
        <NavLink to="/settings" className={navLinkClassName}>
          Settings
        </NavLink>
      </nav>
      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          Log out
        </Button>
      </div>
    </header>
  );
}
