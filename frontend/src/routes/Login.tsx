import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";

import { loginErrorMessage, useLogin } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function Login() {
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const login = useLogin();

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate(password, { onSuccess: () => void navigate("/") });
  }

  return (
    <div className="flex min-h-svh items-center justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-xs space-y-4">
        <h1 className="text-base font-medium">Bedrock</h1>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
        </div>
        {login.isError && (
          <p className="text-destructive text-sm">{loginErrorMessage(login.error)}</p>
        )}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          Log in
        </Button>
      </form>
    </div>
  );
}
