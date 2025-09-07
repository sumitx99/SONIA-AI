"use client"

import type React from "react"

import { useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { PlusSquare, MessageSquare, Sparkles, User, Paperclip, ArrowUp, Bot, Edit2, Trash2 } from "lucide-react"

// Import API functions
import { sendMessage, uploadPDF, handleApiError } from "@/lib/api"

interface Message {
  id: string
  content: string
  sender: "user" | "bot"
  timestamp: Date
}

interface ChatSession {
  id: string
  title: string
  messages: Message[]
  lastMessage: Date
}

export default function SoniaChatInterface() {
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([])
  const [currentChatId, setCurrentChatId] = useState<string | null>(null)
  const [inputValue, setInputValue] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState("")
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  // Get current chat session
  const currentChat = chatSessions.find(chat => chat.id === currentChatId)
  const messages = currentChat?.messages || []

  // Create a new chat session
  const createNewChat = () => {
    const newChatId = Date.now().toString()
    const newChat: ChatSession = {
      id: newChatId,
      title: "New Chat",
      messages: [],
      lastMessage: new Date()
    }
    
    setChatSessions(prev => [newChat, ...prev])
    setCurrentChatId(newChatId)
  }

  // Switch to a different chat
  const switchToChat = (chatId: string) => {
    setCurrentChatId(chatId)
  }

  // Delete a chat session
  const deleteChat = (chatId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setChatSessions(prev => prev.filter(chat => chat.id !== chatId))
    
    if (currentChatId === chatId) {
      const remainingChats = chatSessions.filter(chat => chat.id !== chatId)
      setCurrentChatId(remainingChats.length > 0 ? remainingChats[0].id : null)
    }
  }

  // Start editing chat title
  const startEditingTitle = (chatId: string, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingChatId(chatId)
    setEditingTitle(currentTitle)
  }

  // Save edited title
  const saveEditedTitle = (chatId: string) => {
    if (editingTitle.trim()) {
      setChatSessions(prev => prev.map(chat => 
        chat.id === chatId 
          ? { ...chat, title: editingTitle.trim() }
          : chat
      ))
    }
    setEditingChatId(null)
    setEditingTitle("")
  }

  // Cancel editing
  const cancelEditing = () => {
    setEditingChatId(null)
    setEditingTitle("")
  }

  // Update chat title based on first message
  const updateChatTitle = (chatId: string, firstMessage: string) => {
    const title = firstMessage.length > 30 
      ? firstMessage.substring(0, 30) + "..."
      : firstMessage
    
    setChatSessions(prev => prev.map(chat =>
      chat.id === chatId 
        ? { ...chat, title }
        : chat
    ))
  }

  const handleSendMessage = async () => {
    if (!inputValue.trim()) return

    // Create new chat if none exists
    let chatId = currentChatId
    if (!chatId) {
      createNewChat()
      chatId = Date.now().toString()
    }

    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue,
      sender: "user",
      timestamp: new Date(),
    }

    // Add user message to current chat
    setChatSessions(prev => prev.map(chat =>
      chat.id === chatId
        ? { 
            ...chat, 
            messages: [...chat.messages, userMessage],
            lastMessage: new Date()
          }
        : chat
    ))

    // Update chat title if this is the first message
    if (messages.length === 0) {
      updateChatTitle(chatId, inputValue)
    }

    setInputValue("")
    setIsLoading(true)

    try {
      const response = await sendMessage(inputValue)
      
      const botMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: response.answer,
        sender: "bot",
        timestamp: new Date(),
      }

      // Add bot message to current chat
      setChatSessions(prev => prev.map(chat =>
        chat.id === chatId
          ? { 
              ...chat, 
              messages: [...chat.messages, botMessage],
              lastMessage: new Date()
            }
          : chat
      ))
    } catch (error) {
      console.error('Error sending message:', error)
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: `Sorry, I encountered an error: ${handleApiError(error)}. Please make sure the backend is running.`,
        sender: "bot",
        timestamp: new Date(),
      }

      setChatSessions(prev => prev.map(chat =>
        chat.id === chatId
          ? { 
              ...chat, 
              messages: [...chat.messages, errorMessage],
              lastMessage: new Date()
            }
          : chat
      ))
    } finally {
      setIsLoading(false)
    }
  }

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      alert('Please select a PDF file.')
      return
    }

    // Create new chat if none exists
    let chatId = currentChatId
    if (!chatId) {
      createNewChat()
      chatId = Date.now().toString()
    }

    setIsUploading(true)
    try {
      const response = await uploadPDF(file)
      
      const uploadMessage: Message = {
        id: Date.now().toString(),
        content: `Successfully uploaded "${file.name}" - ${response.chunks_stored} chunks processed. You can now ask questions about this document!`,
        sender: "bot",
        timestamp: new Date(),
      }

      setChatSessions(prev => prev.map(chat =>
        chat.id === chatId
          ? { 
              ...chat, 
              messages: [...chat.messages, uploadMessage],
              lastMessage: new Date(),
              title: messages.length === 0 ? `Chat about ${file.name}` : chat.title
            }
          : chat
      ))
    } catch (error) {
      console.error('Upload error:', error)
      const errorMessage: Message = {
        id: Date.now().toString(),
        content: `Upload failed: ${handleApiError(error)}. Please make sure the backend is running and try again.`,
        sender: "bot",
        timestamp: new Date(),
      }

      setChatSessions(prev => prev.map(chat =>
        chat.id === chatId
          ? { 
              ...chat, 
              messages: [...chat.messages, errorMessage],
              lastMessage: new Date()
            }
          : chat
      ))
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const handleEditKeyPress = (e: React.KeyboardEvent, chatId: string) => {
    if (e.key === "Enter") {
      saveEditedTitle(chatId)
    } else if (e.key === "Escape") {
      cancelEditing()
    }
  }

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-background">
        {/* Left Sidebar */}
        <div className="w-64 bg-sidebar border-r border-sidebar-border flex flex-col">
          {/* New Chat Button */}
          <div className="p-4">
            <Button
              variant="outline"
              className="w-full justify-start gap-2 bg-sidebar-accent hover:bg-sidebar-accent/80 border-sidebar-border text-sidebar-accent-foreground"
              onClick={createNewChat}
            >
              <PlusSquare className="h-4 w-4" />
              New Chat
            </Button>
          </div>

          {/* Chat History */}
          <div className="flex-1 px-4">
            <h3 className="text-sm font-medium text-sidebar-foreground mb-3">Chat History</h3>
            <ScrollArea className="h-full">
              <div className="space-y-2">
                {chatSessions.map((chat) => (
                  <div
                    key={chat.id}
                    className={`group relative rounded-lg ${
                      currentChatId === chat.id ? 'bg-sidebar-accent' : ''
                    }`}
                  >
                    <Button
                      variant="ghost"
                      className={`w-full justify-start gap-2 h-auto p-3 text-left hover:bg-sidebar-accent text-sidebar-foreground hover:text-sidebar-accent-foreground ${
                        currentChatId === chat.id ? 'bg-sidebar-accent text-sidebar-accent-foreground' : ''
                      }`}
                      onClick={() => switchToChat(chat.id)}
                    >
                      <MessageSquare className="h-4 w-4 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        {editingChatId === chat.id ? (
                          <Input
                            value={editingTitle}
                            onChange={(e) => setEditingTitle(e.target.value)}
                            onKeyDown={(e) => handleEditKeyPress(e, chat.id)}
                            onBlur={() => saveEditedTitle(chat.id)}
                            className="text-sm h-auto p-0 border-0 bg-transparent focus-visible:ring-1"
                            autoFocus
                            onClick={(e) => e.stopPropagation()}
                          />
                        ) : (
                          <>
                            <div className="text-sm font-medium truncate">{chat.title}</div>
                            <div className="text-xs text-sidebar-foreground/60">
                              {chat.lastMessage.toLocaleDateString()}
                            </div>
                          </>
                        )}
                      </div>
                    </Button>
                    
                    {/* Action buttons - show on hover */}
                    <div className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 flex gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 hover:bg-sidebar-border"
                        onClick={(e) => startEditingTitle(chat.id, chat.title, e)}
                      >
                        <Edit2 className="h-3 w-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 hover:bg-destructive hover:text-destructive-foreground"
                        onClick={(e) => deleteChat(chat.id, e)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>

          {/* User Profile */}
          <div className="p-4 border-t border-sidebar-border">
            <div className="flex items-center gap-3">
              <Avatar className="h-8 w-8">
                <AvatarFallback className="bg-sidebar-primary text-sidebar-primary-foreground">
                  <User className="h-4 w-4" />
                </AvatarFallback>
              </Avatar>
              <span className="text-sm font-medium text-sidebar-foreground">User</span>
            </div>
          </div>
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col bg-background">
          {/* Chat Messages */}
          <ScrollArea className="flex-1 p-6">
            {messages.length === 0 ? (
              // Welcome Message
              <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
                <Avatar className="h-16 w-16 bg-primary">
                  <AvatarFallback className="bg-primary text-primary-foreground">
                    <Sparkles className="h-8 w-8" />
                  </AvatarFallback>
                </Avatar>
                <div className="space-y-2">
                  <h1 className="text-2xl font-bold text-foreground">Sonia AI</h1>
                  <p className="text-muted-foreground max-w-md text-balance">
                    Your lovable document assistant. Upload a PDF or ask me anything!
                  </p>
                </div>
              </div>
            ) : (
              // Chat Messages
              <div className="space-y-6 max-w-4xl mx-auto">
                {messages.map((message) => (
                  <div
                    key={message.id}
                    className={`flex gap-4 ${message.sender === "user" ? "justify-end" : "justify-start"}`}
                  >
                    {message.sender === "bot" && (
                      <Avatar className="h-8 w-8 bg-primary flex-shrink-0">
                        <AvatarFallback className="bg-primary text-primary-foreground">
                          <Bot className="h-4 w-4" />
                        </AvatarFallback>
                      </Avatar>
                    )}

                    <Card
                      className={`max-w-[70%] p-4 ${
                        message.sender === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-card text-card-foreground"
                      }`}
                    >
                      <p className="text-sm leading-relaxed">{message.content}</p>
                    </Card>

                    {message.sender === "user" && (
                      <Avatar className="h-8 w-8 flex-shrink-0">
                        <AvatarFallback className="bg-muted text-muted-foreground">
                          <User className="h-4 w-4" />
                        </AvatarFallback>
                      </Avatar>
                    )}
                  </div>
                ))}

                {/* Loading Indicator */}
                {isLoading && (
                  <div className="flex gap-4 justify-start">
                    <Avatar className="h-8 w-8 bg-primary flex-shrink-0">
                      <AvatarFallback className="bg-primary text-primary-foreground">
                        <Bot className="h-4 w-4" />
                      </AvatarFallback>
                    </Avatar>
                    <Card className="max-w-[70%] p-4 bg-card text-card-foreground">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">Sonia is typing</span>
                        <div className="flex gap-1">
                          <div className="w-1 h-1 bg-primary rounded-full animate-pulse"></div>
                          <div
                            className="w-1 h-1 bg-primary rounded-full animate-pulse"
                            style={{ animationDelay: "0.2s" }}
                          ></div>
                          <div
                            className="w-1 h-1 bg-primary rounded-full animate-pulse"
                            style={{ animationDelay: "0.4s" }}
                          ></div>
                        </div>
                      </div>
                    </Card>
                  </div>
                )}
              </div>
            )}
          </ScrollArea>

          {/* Message Input Form */}
          <div className="p-6 border-t border-border">
            <Card className="p-4 max-w-4xl mx-auto">
              <div className="flex items-center gap-3">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button 
                      variant="ghost" 
                      size="icon" 
                      className="flex-shrink-0"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={isUploading}
                    >
                      <Paperclip className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {isUploading ? "Uploading..." : "Upload PDF"}
                  </TooltipContent>
                </Tooltip>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  onChange={handleFileUpload}
                  className="hidden"
                />

                <Input
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Ask Sonia about your document or anything else..."
                  className="flex-1 border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0"
                  disabled={isLoading}
                />

                <Button
                  onClick={handleSendMessage}
                  disabled={!inputValue.trim() || isLoading}
                  size="icon"
                  className="flex-shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground"
                >
                  <ArrowUp className="h-4 w-4" />
                </Button>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}