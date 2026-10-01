import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";

import { Header } from "@/components/Header";
import { RequireAuth } from "@/components/RequireAuth";
import { createQueryClient } from "@/lib/query-client";
import { Companies } from "@/routes/Companies";
import { Company } from "@/routes/Company";
import { Login } from "@/routes/Login";
import { Settings } from "@/routes/Settings";

const queryClient = createQueryClient();

function Shell() {
  return (
    <RequireAuth>
      <div className="min-h-svh">
        <Header />
        <main>
          <Outlet />
        </main>
      </div>
    </RequireAuth>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Shell />}>
        <Route index element={<Companies />} />
        <Route path="settings" element={<Settings />} />
        <Route path="c/:ticker/:tab?" element={<Company />} />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
