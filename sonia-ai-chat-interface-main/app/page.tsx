import Link from "next/link";
import {
  ArrowUpRight,
  ArrowDown,
  Plus,
  FileText,
  CornerDownRight,
} from "lucide-react";
import { Brand, Emblem } from "@/components/brand";
import { Reveal } from "@/components/reveal";
import { ConversationPreview } from "@/components/conversation-preview";
import { LandingMotion, MotionToggle } from "@/components/landing-motion";
import {
  SculptureStage,
  StudioHeadline,
  ReadingManifesto,
} from "@/components/studio-motion";
import { GlassMethodCards } from "@/components/glass-method-cards";
import { HeroCursor } from "@/components/hero-cursor";
import "./landing.css";

export default function LandingPage() {
  return (
    <LandingMotion className="studio-site">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <main id="main">
        <div className="studio-dark">
          <header className="studio-header studio-wrap">
            <Brand light />
            <nav aria-label="Main navigation">
              <a href="#approach">The philosophy</a>
              <a href="#workspace">The experience</a>
              <a href="#about">The maker</a>
            </nav>
            <div className="studio-header-actions">
              <MotionToggle />
              <Link href="/chat" className="studio-header-cta">
                Enter Sonia <ArrowUpRight size={16} />
              </Link>
            </div>
          </header>
          <section className="studio-hero studio-wrap">
            {/* Only "Old soul." opens the selection box. */}
            <HeroCursor target=".studio-headline-line:first-child" />
            <div className="studio-hero-top">
              <span>
                <i /> INTELLIGENCE WITH A DIFFERENT SOUL
              </span>
              <span>FOR THE CURIOUS / VOL. 01</span>
            </div>
            <SculptureStage />
            <div className="studio-hero-copy">
              <StudioHeadline />
              <Reveal delay={0.25}>
                <p>
                  Your documents have a story.
                  <br />
                  Find the part that matters.
                </p>
                <div className="studio-hero-actions">
                  <Link
                    href="/chat"
                    className="studio-button studio-button-red"
                  >
                    Meet your new mind <ArrowUpRight size={20} />
                  </Link>
                  <a href="#workspace" className="studio-inline-link">
                    See it in thought <span>↗</span>
                  </a>
                </div>
              </Reveal>
            </div>
            <div className="studio-hero-bottom">
              <span className="studio-micro">
                YOUR DOCUMENTS. YOUR QUESTIONS. YOUR NEXT DISCOVERY.
              </span>
              <a href="#approach">
                SCROLL TO EXPLORE <ArrowDown size={14} />
              </a>
            </div>
          </section>
        </div>
        <div
          className="studio-ribbon"
          aria-label="Read deeply, think freely, ask anything"
        >
          <div>
            {[0, 1].map((copy) => (
              <div key={copy} aria-hidden={copy === 1 ? true : undefined}>
                <span>READ DEEPLY</span>
                <Emblem />
                <span>THINK FREELY</span>
                <Emblem />
                <span>ASK ANYTHING</span>
                <Emblem />
                <span>FIND YOUR THREAD</span>
                <Emblem />
              </div>
            ))}
          </div>
        </div>
        <section id="approach" className="studio-philosophy studio-wrap">
          <Reveal className="studio-section-label">
            <span>01 / THE PHILOSOPHY</span>
            <span>LESS SEARCHING. MORE SEEING.</span>
          </Reveal>
          <ReadingManifesto />
          <GlassMethodCards
            steps={[
              {
                n: "I",
                label: "The pages",
                title: "Bring the pages.",
                art: "pages",
                text: "The research paper. The annual report. That PDF you keep putting off. Give your documents somewhere to become useful.",
              },
              {
                n: "II",
                label: "The thread",
                title: "Pull on a thread.",
                art: "thread",
                text: "Ask a question, follow a detail, find the connection. A good conversation takes you further than a search bar.",
              },
              {
                n: "III",
                label: "The clarity",
                title: "Leave with clarity.",
                art: "clarity",
                text: "Answers grounded in your documents. A fresh perspective on what matters. Room for your next good idea.",
              },
            ]}
          />
        </section>
        <section id="workspace" className="studio-experience">
          <div className="studio-wrap">
            <Reveal className="studio-section-label">
              <span>02 / THE EXPERIENCE</span>
              <span>AN ILLUSTRATIVE CONVERSATION</span>
            </Reveal>
            <Reveal className="studio-demo-heading">
              <h2>
                A meeting
                <br />
                of <em>minds.</em>
                <span className="studio-heading-star">✳</span>
              </h2>
              <p>
                You bring the question.
                <br />
                Sonia finds the thread.
                <br />
                <span>Watch a thought take shape below.</span>
              </p>
            </Reveal>
            <Reveal className="studio-demo-frame">
              <div className="studio-demo-bar">
                <span>
                  <i />
                  <i />
                  <i />
                </span>
                <span>SONIA / THE READING ROOM</span>
                <Emblem />
              </div>
              <div className="studio-demo-content">
                <aside className="studio-demo-sidebar">
                  <Brand />
                  <span className="studio-demo-new">
                    <Plus size={13} /> New conversation
                  </span>
                  <span className="studio-micro">ON YOUR DESK</span>
                  <span className="studio-demo-file">
                    <FileText size={15} /> The creative process.pdf
                  </span>
                  <div>
                    <Emblem />
                    <p>
                      A little room
                      <br />
                      for a bigger thought.
                    </p>
                  </div>
                </aside>
                <div className="studio-demo-chat">
                  <ConversationPreview />
                </div>
              </div>
            </Reveal>
            <div className="studio-demo-caption">
              <span>NO SCRIPT TO LEARN. JUST FOLLOW YOUR CURIOSITY.</span>
              <Link href="/chat">
                Try your own question <CornerDownRight size={15} />
              </Link>
            </div>
          </div>
        </section>
        <section id="about" className="studio-maker studio-wrap">
          <Reveal className="studio-maker-seal">
            <div>
              <Emblem />
              <span>
                HUMAN CURIOSITY
                <br />
                MEETS MACHINE INTELLIGENCE
              </span>
            </div>
            <span>BUILT WITH INTENTION. ALWAYS.</span>
          </Reveal>
          <Reveal className="studio-maker-copy">
            <span className="studio-micro">03 / A NOTE FROM THE MAKER</span>
            <h2>
              Made for the
              <br />
              <em>beautifully curious.</em>
            </h2>
            <p>
              Built by Sumit Kumar Ranjan, Sonia gives your documents a place to
              become a conversation. A companion for research, reading, and
              questions that deserve a closer look.
            </p>
            <div>
              <span>Sumit Kumar Ranjan</span>
              <span>CREATOR OF SONIA</span>
            </div>
          </Reveal>
        </section>
        <section className="studio-finale">
          <div className="studio-wrap">
            <Reveal>
              <span className="studio-micro">
                YOUR NEXT GOOD IDEA IS IN THERE.
              </span>
              <h2>
                Go on.
                <br />
                <em>Open your mind.</em>
              </h2>
              <Link href="/chat" className="studio-finale-link">
                Enter the reading room{" "}
                <ArrowUpRight size={38} strokeWidth={1} />
              </Link>
            </Reveal>
            <Emblem className="studio-finale-emblem" />
          </div>
        </section>
      </main>
      <footer className="studio-footer studio-wrap">
        <Brand />
        <span>A different kind of intelligence.</span>
        <a href="#main">
          BACK TO THE TOP <ArrowUpRight size={14} />
        </a>
      </footer>
    </LandingMotion>
  );
}
