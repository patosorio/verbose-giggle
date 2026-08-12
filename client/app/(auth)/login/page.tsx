import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MagicLinkRequestForm } from "@/components/auth/MagicLinkRequestForm";

export default function LoginPage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-2xl">Travel</CardTitle>
          <CardDescription>
            Enter your email and we&apos;ll send you a magic link to sign in.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MagicLinkRequestForm />
        </CardContent>
      </Card>
    </main>
  );
}
