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
} from "@/components/studio-motion";
import { SourceProcess } from "@/components/source-process";
import { HeroCursor } from "@/components/hero-cursor";

import "./landing.css";
import "./cinematic.css";

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
              <a href="#approach">The process</a>
              <a href="#workspace">In action</a>
              <a href="#about">Behind Sonia</a>
            </nav>
            <div className="studio-header-actions">
              <MotionToggle />
              <Link href="/chat" className="studio-header-cta">
                Enter Sonia <ArrowUpRight size={16} />
              </Link>
            </div>
          </header>
          <section className="studio-hero studio-wrap">
            <HeroCursor target=".studio-headline-line:first-child" />

            <div className="studio-hero-top">
              <span>
                <i /> A DIFFERENT KIND OF INTELLIGENCE
              </span>
              <span>DOCUMENTS. QUESTIONS. DISCOVERIES.</span>
            </div>
            <div className="cinema-disc" aria-hidden="true" />
            <div className="cinema-backdrop-word" aria-hidden="true">SONIA</div>
            <SculptureStage />
            <div className="studio-hero-copy">
              <StudioHeadline />
              <Reveal delay={0.25}>
                <p>
                  Every document holds a discovery.
                  <br />
                  Ask the question. Find yours.
                </p>
                <div className="studio-hero-actions">
                  <Link
                    href="/chat"
                    className="studio-button studio-button-red"
                  >
                    Start exploring <ArrowUpRight size={20} />
                  </Link>
                  <a href="#workspace" className="studio-inline-link">
                    Watch it work <span>↗</span>
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
            <span>01 / THE PROCESS</span>
            <span>LESS SEARCHING. MORE SEEING.</span>
          </Reveal>
          <Reveal className="method-intro">
            <h2>Your documents.<br /><em>A new perspective.</em></h2>
            <p>A shorter path from reading to understanding. Bring a document, follow your curiosity, and keep the source in sight.</p>
          </Reveal>
          <SourceProcess />
        </section>
        <section id="workspace" className="studio-experience">
          <div className="studio-wrap">
            <Reveal className="studio-section-label">
              <span>02 / IN ACTION</span>
              <span>AN ILLUSTRATIVE CONVERSATION</span>
            </Reveal>
            <Reveal className="studio-demo-heading">
              <h2>
                GO DEEPER.<br /><em>SEE IT CLEARER.</em>

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
          <Reveal className="maker-index"><span className="studio-micro">A PERSONAL PROJECT</span><span className="maker-monogram">S<span>.</span></span><span>Built for the questions<br />worth spending time with.</span></Reveal>
          <Reveal className="studio-maker-copy">
            <span className="studio-micro">03 / A NOTE FROM THE MAKER</span>
            <h2>
              BUILT FOR<br /><em>THE CURIOUS.</em>
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
                LESS SCROLLING.<br /><em>MORE KNOWING.</em>
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
