import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { FileText, MessageSquare, Sparkles, Zap, Shield, Clock, ArrowRight, Star } from "lucide-react"

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Navigation */}
      <nav className="border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-2">
              <Sparkles className="h-8 w-8 text-primary" />
              <span className="text-xl font-bold text-foreground">Sonia AI</span>
            </div>
            <div className="flex items-center gap-4">
              <Link href="/auth">
                <Button variant="ghost">Sign In</Button>
              </Link>
              <Link href="/chat">
                <Button>Try Chat</Button>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8">
        <div className="container mx-auto text-center">
          <Badge variant="secondary" className="mb-4">
            AI-Powered Document Assistant
          </Badge>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-foreground mb-6 text-balance">
            Your Clari Document Assistant
          </h1>
          <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto text-pretty">
            Upload PDFs, ask questions, and get intelligent answers. Sonia makes document analysis effortless and
            engaging.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/chat">
              <Button size="lg" className="text-lg px-8">
                Try Sonia Now
                <ArrowRight className="ml-2 h-5 w-5" />
              </Button>
            </Link>
            <Button variant="outline" size="lg" className="text-lg px-8 bg-transparent">
              Watch Demo
            </Button>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 bg-muted/50">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">
              Powerful Features for Document Analysis
            </h2>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
              Everything you need to understand, analyze, and interact with your documents.
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            <Card className="border-border">
              <CardHeader>
                <FileText className="h-12 w-12 text-primary mb-4" />
                <CardTitle>PDF Analysis</CardTitle>
                <CardDescription>
                  Upload any PDF and get instant insights. Extract key information, summaries, and answers to your
                  questions.
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="border-border">
              <CardHeader>
                <MessageSquare className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Interactive Chat</CardTitle>
                <CardDescription>
                  Have natural conversations about your documents. Ask follow-up questions and dive deeper into the
                  content.
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="border-border">
              <CardHeader>
                <Zap className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Lightning Fast</CardTitle>
                <CardDescription>
                  Get answers in seconds, not minutes. Our AI processes documents quickly while maintaining accuracy.
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="border-border">
              <CardHeader>
                <Shield className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Secure & Private</CardTitle>
                <CardDescription>
                  Your documents are processed securely and never stored permanently. Privacy is our top priority.
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="border-border">
              <CardHeader>
                <Clock className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Chat History</CardTitle>
                <CardDescription>
                  Keep track of all your conversations and easily return to previous document analyses.
                </CardDescription>
              </CardHeader>
            </Card>

            <Card className="border-border">
              <CardHeader>
                <Sparkles className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Smart Insights</CardTitle>
                <CardDescription>
                  Get intelligent summaries, key points, and contextual understanding of complex documents.
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </div>
      </section>

      {/* Testimonials Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">Loved by Users Worldwide</h2>
            <p className="text-xl text-muted-foreground">See what people are saying about Sonia AI</p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            <Card className="border-border">
              <CardContent className="pt-6">
                <div className="flex mb-4">
                  {[...Array(5)].map((_, i) => (
                    <Star key={i} className="h-5 w-5 fill-primary text-primary" />
                  ))}
                </div>
                <p className="text-card-foreground mb-4">
                  "Sonia has revolutionized how I handle research papers. The AI understands context incredibly well!"
                </p>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-primary rounded-full flex items-center justify-center text-primary-foreground font-semibold">
                    S
                  </div>
                  <div>
                    <p className="font-semibold text-card-foreground">Shubham Raj</p>
                    <p className="text-sm text-muted-foreground">Software Engineer</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border">
              <CardContent className="pt-6">
                <div className="flex mb-4">
                  {[...Array(5)].map((_, i) => (
                    <Star key={i} className="h-5 w-5 fill-primary text-primary" />
                  ))}
                </div>
                <p className="text-card-foreground mb-4">
                  "The chat interface is so intuitive. It feels like having a conversation with a knowledgeable
                  colleague."
                </p>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-primary rounded-full flex items-center justify-center text-primary-foreground font-semibold">
                    M
                  </div>
                  <div>
                    <p className="font-semibold text-card-foreground">Akshit Sharma </p>
                    <p className="text-sm text-muted-foreground">Machine learning enginner</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="border-border">
              <CardContent className="pt-6">
                <div className="flex mb-4">
                  {[...Array(5)].map((_, i) => (
                    <Star key={i} className="h-5 w-5 fill-primary text-primary" />
                  ))}
                </div>
                <p className="text-card-foreground mb-4">
                  "I save hours every week using Sonia to analyze contracts and reports. It's incredibly accurate."
                </p>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-primary rounded-full flex items-center justify-center text-primary-foreground font-semibold">
                    A
                  </div>
                  <div>
                    <p className="font-semibold text-card-foreground">Madhav Arya</p>
                    <p className="text-sm text-muted-foreground">Business Consultant</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>
      {/* Meet the Creator Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 bg-muted/50">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">Meet the Creator</h2>
            <p className="text-xl text-muted-foreground">Built with passion by a dedicated software engineer</p>
          </div>

          <div className="max-w-4xl mx-auto">
            <Card className="border-border">
              <CardContent className="p-8">
                <div className="flex flex-col lg:flex-row items-center gap-8">
                  <div className="flex-shrink-0">
                    <img
                      src="https://i.ibb.co/3mYFS506/Whats-App-Image-2025-08-18-at-21-44-25-b0ef52e2.jpg"
                      alt="Sumit Kumar Ranjan"
                      className="w-48 h-48 rounded-full object-cover border-4 border-primary/20"
                    />
                  </div>
                  <div className="flex-1 text-center lg:text-left">
                    <h3 className="text-2xl font-bold text-foreground mb-2">Sumit Kumar Ranjan</h3>
                    <p className="text-lg text-primary font-semibold mb-4">Software Engineer</p>
                    <p className="text-muted-foreground mb-6 leading-relaxed">
                      Passionate about creating AI-powered solutions that make complex tasks simple and accessible. With
                      expertise in modern web technologies and artificial intelligence, Sumit built Sonia AI to
                      revolutionize how people interact with documents and information.
                    </p>
                    <div className="flex flex-wrap gap-2 justify-center lg:justify-start">
                      <Badge variant="secondary">AI Development</Badge>
                      <Badge variant="secondary">Full-Stack Engineering</Badge>
                      <Badge variant="secondary">Document Processing</Badge>
                      <Badge variant="secondary">User Experience</Badge>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-4 sm:px-6 lg:px-8 bg-muted/50">
        <div className="container mx-auto text-center">
          <h2 className="text-3xl sm:text-4xl font-bold text-foreground mb-4">
            Ready to Transform Your Document Workflow?
          </h2>
          <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
            Join thousands of users who trust Sonia AI for their document analysis needs.
          </p>
          <Link href="/chat">
            <Button size="lg" className="text-lg px-8">
              Start Chatting with Sonia
              <ArrowRight className="ml-2 h-5 w-5" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-border py-12 px-4 sm:px-6 lg:px-8">
        <div className="container mx-auto">
          <div className="flex flex-col md:flex-row justify-between items-center">
            <div className="flex items-center gap-2 mb-4 md:mb-0">
              <Sparkles className="h-6 w-6 text-primary" />
              <span className="text-lg font-semibold text-foreground">Sonia AI</span>
            </div>
            <div className="flex gap-6 text-sm text-muted-foreground">
              <Link href="/privacy" className="hover:text-foreground transition-colors">
                Privacy Policy
              </Link>
              <Link href="/terms" className="hover:text-foreground transition-colors">
                Terms of Service
              </Link>
              <Link href="/contact" className="hover:text-foreground transition-colors">
                Contact
              </Link>
            </div>
          </div>
          {/* <div className="mt-8 pt-8 border-t border-border text-center text-sm text-muted-foreground">
            © 2025 Sonia AI. All rights reserved.
          </div> */}
          <div className="mt-8 pt-8 border-t border-border text-center text-sm text-muted-foreground">
            © Created by SUMIT KUMAR RANJAN
          </div>
        </div>
      </footer>
    </div>
  )
}
