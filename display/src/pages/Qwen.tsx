import React, { useState, useEffect } from 'react';
import { LLMMessage } from '../components/LLMMessage';
import { useWebSocketConnection } from '../hooks/useWebSocket';

export default function Qwen() {
  const [phase, setPhase] = useState<'listening' | 'animating' | 'streaming'>('listening');
  const wsUrl = `ws://${window.location.hostname}:8080`;
  const { message } = useWebSocketConnection(wsUrl);

  useEffect(() => {
    // When a message is received, trigger the animation phase
    if (message && phase === 'listening') {
      setPhase('animating');
    }
  }, [message, phase]);

  useEffect(() => {
    if (phase === 'animating') {
      const timer = setTimeout(() => {
        setPhase('streaming');
      }, 1200); // 1.2s transition time
      return () => clearTimeout(timer);
    }
  }, [phase]);

  // Extract content from message
  const getContent = () => {
    if (!message) return '';
    try {
      const parsed = JSON.parse(message);
      return parsed.content || parsed.text || parsed.data || message;
    } catch (e) {
      return message;
    }
  };

  const content = getContent();

  return (
    <div className="min-h-screen bg-[#121212] relative overflow-hidden font-sans text-white">
      {/* Header gap simulation */}
      <div className="h-20 flex items-center justify-center text-gold-gradient text-4xl tracking-widest bg-black/50"
          style={{ fontFamily: 'Bietro' }}>
        QWEN
      </div>

      {/* Main Content Area */}
      <div className="relative p-8 h-[calc(100vh-4rem)] flex justify-center items-center">
        
        {/* Streaming text area box */}
        <div className={`transition-opacity duration-1000 ease-in-out w-full max-w-4xl h-full max-h-[70vh] p-12 flex items-center justify-center mt-8 ml-16 relative ${phase === 'streaming' ? 'opacity-100' : 'opacity-0'}`}>
          {phase === 'streaming' ? (
             <div className="w-full h-full text-left overflow-auto">
               <LLMMessage content={content} fontSize="text-lg" animate={true} speed={20} />
             </div>
          ) : (
             <div className="text-white/40">text streamed here</div>
          )}
        </div>

        {/* The Animated Logo Container */}
        <div 
          onClick={() => { if(phase === 'listening') setPhase('animating') }}
          className={`fixed transition-all duration-[1200ms] ease-in-out cursor-pointer flex flex-col items-center justify-center z-50 ${
            phase === 'listening' 
              ? 'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 scale-100 rotate-0' 
              : 'top-8 left-8 translate-x-0 translate-y-0 scale-[0.6] -rotate-[360deg]'
          }`}
        >
          {/* Logo Circle with Construction Lines */}
          <div className="w-64 h-64 rounded-full border border-[#FFDB86] flex items-center justify-center bg-black relative overflow-hidden">
            {/* Construction lines matching the image */}
            <div className="absolute top-1/2 left-0 w-full h-[1px] bg-[#FFDB86]/50"></div>
            <div className="absolute top-0 left-1/2 w-[1px] h-full bg-[#FFDB86]/50"></div>
            <div className="absolute top-1/4 left-1/4 w-1/2 h-1/2 border border-[#FFDB86]/50 rotate-45"></div>
            <div className="absolute top-1/4 left-1/4 w-1/2 h-1/2 border border-[#FFDB86]/50 rounded-full"></div>
            
            <img 
              src="/qwen.png" 
              alt="Qwen Logo" 
              className="w-32 h-32 object-contain relative z-10" 
            />
          </div>

          {/* Listening Text */}
          <div className={`absolute -bottom-12 text-sm text-[#FFDB86] transition-opacity duration-300 font-medium tracking-widest ${phase === 'listening' ? 'opacity-100' : 'opacity-0'}`}>
            LISTENING..
          </div>
        </div>

      </div>
    </div>
  );
}
