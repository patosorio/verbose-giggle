"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api-client";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
}

type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  accessToken: string | null;
  user: AuthUser | null;
  status: AuthStatus;
  setAuth: (token: string, user: AuthUser) => void;
  clearAuth: () => void;
}

const ACCESS_TOKEN_KEY = "access_token";
const USER_KEY = "user";

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [hasHydrated, setHasHydrated] = useState(false);

  const clearAuth = useCallback(() => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  const setAuth = useCallback((token: string, nextUser: AuthUser) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(nextUser));
    setAccessToken(token);
    setUser(nextUser);
    setStatus("authenticated");
  }, []);

  useEffect(() => {
    const storedToken = localStorage.getItem(ACCESS_TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (storedToken && storedUser) {
      try {
        setAccessToken(storedToken);
        setUser(JSON.parse(storedUser) as AuthUser);
        // status stays "loading" — the useQuery below confirms the token is still valid.
      } catch {
        localStorage.removeItem(ACCESS_TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        setStatus("unauthenticated");
      }
    } else {
      setStatus("unauthenticated");
    }
    setHasHydrated(true);
  }, []);

  const { data, isError } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => apiFetch<AuthUser>("/auth/me", { token: accessToken }),
    enabled: hasHydrated && !!accessToken,
    retry: false,
  });

  useEffect(() => {
    if (!data) return;
    setUser(data);
    localStorage.setItem(USER_KEY, JSON.stringify(data));
    setStatus("authenticated");
  }, [data]);

  useEffect(() => {
    if (isError) {
      clearAuth();
    }
  }, [isError, clearAuth]);

  const value = useMemo<AuthContextValue>(
    () => ({ accessToken, user, status, setAuth, clearAuth }),
    [accessToken, user, status, setAuth, clearAuth]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

export function useUpdateDisplayName() {
  const { accessToken, setAuth } = useAuth();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (display_name: string) =>
      apiFetch<AuthUser>("/auth/me", {
        method: "PATCH",
        body: { display_name },
        token: accessToken,
      }),
    onSuccess: (updatedUser) => {
      if (accessToken) {
        setAuth(accessToken, updatedUser);
      }
      queryClient.setQueryData(["auth", "me"], updatedUser);
    },
  });
}
