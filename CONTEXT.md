# Email assistant

A chat assistant that researches content, reads the inbox, and sends outbound email on the user's behalf.

## Language

**Chat message**:
A user or assistant utterance in the conversation that drives research, inbox reading, or sending.
_Avoid_: request, prompt, contents

**Assistant reply**:
The assistant's Chat message. It is written in the language of the user's Chat message, and it carries no offer of further work.
_Avoid_: outbound email body, assistant offer

**Recipient**:
The address that receives an outbound email. Precedence is pinned, then named, then the default inbox.
_Avoid_: to_email, destination, target

**Pinned recipient**:
The Recipient chosen in the chat UI. It stays until the human changes it and applies to the next Chat message that creates a Draft, except a Reply. It does not change the Recipient of an open Draft.
_Avoid_: UI email, selected email, to_email

**Named recipient**:
A Recipient stated in the Chat message and passed into the send tool.
_Avoid_: tool email, explicit to_email

**Default inbox**:
The user's own inbox address, used when neither pinned nor named.
_Avoid_: EMAIL_ADDRESS, from_email, primary email

**Inbound email**:
An email already in the user's inbox, apart from the Session. It is not an Outbound email and not a Draft. The chrome lists the ten most recent from the last seven days, read and unread. In the sidebar list, a long sender or subject is cut off. The opened email shows both in full. The human may open one and read its sender, subject, date, and body without creating a Reply. The body shown is plain text. An attachment is not shown. An empty body still shows the sender, subject, and date, and a Reply can still be chosen. Opening the body marks that email read in the inbox and clears its unread mark. Listing them does not. An Arrival notice that opens a Reply does not mark the email read. If marking it read fails, the body stays open, the unread mark stays, and an Interface alert reports the failure. That opening covers the conversation and does not end the Session. A Chat message closes it. Going back shows the list when the Session is empty, and the conversation when it is not.
_Avoid_: message, recent chat, notification

**Reply**:
A Draft that answers one Inbound email. Its Recipient is that email's sender. Its subject starts with "Re:" plus that email's subject; an existing "Re:" is kept once, and an empty subject stays "Re:". The body answers that email and does not include the Inbound email's body or its attachments. An empty Inbound email body leaves the Reply to answer from the subject. The Pinned recipient does not apply. The human chooses the Inbound email with a separate action after reading it, or a Chat message that identifies it. That separate action waits while a Chat message is in flight. An Arrival notice opens the Reply when no Draft is open and no Chat message is in flight. If the Inbound email's language cannot be told and the Chat message does not ask for one, the Reply uses Portuguese. If the Chat message matches more than one Inbound email, the Assistant reply asks which, by sender, subject, and date, and no Reply is created.
_Avoid_: Assistant reply, auto-send

**Baseline**:
The Inbound emails from the last successful listing. The first successful listing after the page loads raises no Arrival notice. A later listing raises one only for an Inbound email that was not in the Baseline. A failed listing does not change it.
_Avoid_: snapshot, cache, first page

**Arrival notice**:
A notice from the chrome, while its tab is visible, that an Inbound email arrived after the Baseline. It names the sender and the subject. Choosing either opens that Inbound email, which does not Dismiss the notice and does not create a Reply. It stands at the top of the conversation area, newest first, and does not cover a Review card. Returning to the tab looks again. When no Draft is open and no Chat message is in flight, the newest arrival in that check opens one Reply and that notice is gone. The others stay notices. When a Draft is open, or a Chat message is in flight, the notice waits. Dismiss stays available during that turn. The human's choice of a Reply from the chrome waits until the turn ends. After the turn, if no Draft is open, the newest waiting arrival opens one Reply. Otherwise it waits until the human asks for the Reply or Dismisses the notice. A Reply for that Inbound email removes its notice. It is not an Interface alert and not an Assistant reply.
_Avoid_: push notification, error banner

**Dismiss**:
The human action that removes one Arrival notice. It does not create a Reply and it does not Discard a Draft. There is no action that removes every notice at once.
_Avoid_: Discard, delete, cancel

**Outbound email**:
An email to a Recipient, with a subject and a body in the same language. Unsent, it is a Draft; SMTP runs only after Confirm.
_Avoid_: message (that is a Chat message)

**Draft**:
An unsent Outbound email stored by the assistant for human review. The human may edit subject, Outbound email body, and Recipient before Confirm.
_Avoid_: Gmail draft, rascunho, pending send

**Review card**:
The editable surface of one open Draft: subject, Outbound email body, and Recipient, kept apart from the conversation while the human writes, and locked while a Chat message is in flight. Confirm and Discard take whatever was on it when the human acted; a refresh restores the stored Draft, and unconfirmed edits are gone.
_Avoid_: form, email editor, draft panel

**Confirm**:
The human action that sends a Draft via SMTP. Subject, Outbound email body, and Recipient are whatever stands on the review card, even when the body has no Opening or Closing. After Confirm, that card is the sent Outbound email, no longer a Draft, and it joins the conversation at that moment.
_Avoid_: approve, OK, send now

**Discard**:
The human action that abandons a Draft so it cannot be Confirmed. The abandoned Draft joins the conversation at that moment and stays visible until the Session ends.
_Avoid_: delete, cancel, reject

**Interface alert**:
A notice from the chrome that a Chat message, a Recipient, a Confirm, a Revision, a Reply, loading Inbound emails, or marking one read failed. A failed Revision leaves the Review card unchanged. A failed Reply leaves no Draft. On the first load, a failed listing leaves no Inbound emails shown. A later failed listing leaves those already shown. If marking an opened Inbound email read fails, the body stays open and the unread mark stays. It is not an Assistant reply and it is not part of the conversation.
_Avoid_: error bubble, assistant error, chat error

**Outbound email body**:
The send-ready plain-text body of an Outbound email: an Opening, the content, a Lead-in when that content needs introducing, and a Closing. Its language is the one the Chat message asks for, otherwise the language that Chat message is written in. A Reply opened without a Chat message uses the language of that Inbound email. If that language cannot be told, the Reply uses Portuguese. It carries no offer of further work.
_Avoid_: contents, signature, body text, assistant offer

**Primary language**:
Portuguese or English, the two languages with a default Opening ("Olá," / "Hello,") and a fixed Closing. A Chat message may replace that Opening with a stated form. Any other language still has an Opening and a Closing, in the conventional form of that language.
_Avoid_: locale, interface language

**Interface language**:
Portuguese, the language of the chrome the human reads. It is independent of the Primary language of an Outbound email body.
_Avoid_: Primary language, locale

**Opening**:
The first line of an Outbound email body. When the Chat message states a relationship or a greeting form, the Opening uses that form. When it states a person's name and no such form, it greets them by that name: "Olá," in Portuguese, "Hello," in English, and a conventional greeting in any other language. On a Reply, if the Chat message states neither a form nor a name, the Opening uses the sender's name on that Inbound email. An address alone is not a name. When no name is known, it greets without a name. The form is not kept for a later Draft.
_Avoid_: lead-in, introduction, cumprimento, contact book

**Lead-in**:
A sentence of the Outbound email body that introduces the content when that content needs introducing.
_Avoid_: opening, introduction, preamble

**Closing**:
The last line of an Outbound email body, with no signature name after it: "Até mais!" in Portuguese, "Talk soon!" in English, and a conventional farewell in any other language.
_Avoid_: saudação, signature, sign-off

**Session**:
The on-screen lifetime of the conversation: Chat messages, Assistant replies, sent Outbound emails, and abandoned Drafts. An open Draft stays available while the human writes, apart from that flow. Opening an Inbound email, choosing a Reply from the chrome, and an Arrival notice add nothing to the Session. A Chat message closes an opened Inbound email. Refresh and Clear chat end the Session. Open Drafts stored by the assistant come back on the next load. Already sent Outbound emails stay sent.
_Avoid_: history, recent chats, thread

**Clear chat**:
The human action that empties the Session and Discards every open Draft. Already sent Outbound emails stay sent. It closes an opened Inbound email and shows the list. Inbound emails stay listed.
_Avoid_: delete, reset, clear drafts

**Revision**:
A Chat message that updates one open Draft in place — the latest, when it is the only one — because the human asked to change that email. It keeps that Draft's language unless the Chat message asks for another. It does not add a card to the conversation. The same message may also create another Draft, and with no open Draft, or with several and none identified, the update does not happen. When the Draft is identified, or it is the only one open, the Revision is complete only when that same turn shows the new subject and body on the Review card. If that update does not happen, the card stays as it was and an Interface alert reports the failure. The Assistant reply says the Draft is ready only after the update.
_Avoid_: regenerate, new draft

**Prior recipient**:
A Recipient address from a Confirmed Draft, offered as the human types a Pinned recipient. The same address appears once, most recent Confirm first, and it does not carry a person's name.
_Avoid_: contact, contact book, Google contact, open draft, discarded draft

**Evaluation case**:
A synthetic turn: one Chat message, plus the Pinned recipient, open Drafts, and Inbound emails that turn needs. It is not a Session.
_Avoid_: fixture, prompt, dataset row, live inbox

**Turn accuracy**:
Whether an Evaluation case passed. The Draft outcome, the Assistant reply, and the facts required of the Outbound email body match what the case requires.
_Avoid_: exact match, latency, cost

**Experiment**:
A run of Evaluation cases. Turn accuracy decides the pass. The turn's latency and cost are kept with the run and do not decide the pass.
_Avoid_: Session, live inbox
