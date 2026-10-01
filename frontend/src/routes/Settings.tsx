import { ThemeToggle } from "@/components/ThemeToggle";

export function Settings() {
  return (
    <div className="flex items-center justify-between p-4">
      <span className="text-sm">Theme</span>
      <ThemeToggle />
    </div>
  );
}
