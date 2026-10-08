# Frontier AI Pipeline: Technical Documentation

This document uses ASD-STE100 Simplified Technical English (STE).
Writing rules are in the section "Writing rules for this document".

## 1 Introduction

### 1.1 Purpose

This document tells you what the Frontier AI Pipeline repository contains.
It also tells you how to change and publish the pages.

### 1.2 Scope

The repository contains three static web pages.
The pages support the Frontier AI Pipeline OAuth application.

The pipeline code is not in this repository.
This document does not describe the pipeline code.

### 1.3 What the application does

The application is a private tool.
One YouTube creator uses it to make the series *Frontier AI, Explained*.
The series gives short animated explanations of new AI research papers.

The application does these tasks:

- It uploads the creator's own videos, captions, and thumbnails to the creator's own YouTube channel. Each upload is a private draft. The creator reviews each draft by hand.
- It reads comments on those videos.
- It reads view counts, watch time, and audience-retention reports for those videos.

The application is not for other users.

## 2 Repository contents

| File           | Purpose                                              |
|----------------|------------------------------------------------------|
| `index.html`   | Home page. Describes the application and its purpose. |
| `privacy.html` | Privacy policy. Lists the data that the application uses. |
| `terms.html`   | Terms of use. States that only the operator uses the tool. |
| `docs/`        | This documentation.                                  |

Each page is one HTML file.
Each page has its own internal style rules.
No page uses a script, a build step, or an outside file.

### 2.1 Page links

- The home page links to the YouTube channel, the privacy policy, and the terms.
- The privacy policy links to these pages:
  - Google account permissions
  - Google API Services User Data Policy
  - YouTube Terms of Service
  - Google Privacy Policy
- The terms page links to the YouTube Terms of Service.

## 3 Description of the application behavior

### 3.1 Google API access

The application uses two Google APIs.

| API                  | Use                                                                        |
|----------------------|----------------------------------------------------------------------------|
| YouTube Data API     | Upload videos, captions, and thumbnails as private drafts. Read comments. |
| YouTube Analytics API| Read view counts, watch time, and audience-retention reports.             |

The application accesses only the operator's own channel.

### 3.2 Data use and storage

- The operator uses analytics data to improve future videos.
- Aggregated reports stay in the operator's private code repository.
- OAuth credentials stay as encrypted secrets in the operator's private GitHub repository.
- Only the automated jobs of that repository use the credentials.
- The application does not sell data.
- The application does not share data with third parties.
- The application does not use data for advertising.
- The application does not collect viewer data. It uses only the aggregate statistics that YouTube gives to channel owners.

### 3.3 Compliance

The application follows these rules:

- Google API Services User Data Policy, including the Limited Use requirements
- YouTube Terms of Service
- Google Privacy Policy

## 4 Procedures

### 4.1 Preview the pages on your computer

Prerequisite: a web browser.

1. Open a terminal in the repository folder.
2. Do this command to start a local web server:

   `python3 -m http.server 8000`

3. Open `http://localhost:8000/` in your browser.
4. Examine each page.
5. Press Ctrl+C in the terminal to stop the server.

You can also open `index.html` directly in a browser.

### 4.2 Change the text of a page

1. Open the applicable HTML file in a text editor.
2. Change the text between the HTML tags.
3. Save the file.
4. Do the procedure in section 4.1 to examine the change.
5. Commit the change with a clear message.

### 4.3 Change the privacy policy

> **WARNING**
> A change to `privacy.html` can change the legal statements about data use.
> Make sure that each statement is true before you publish it.

1. Open `privacy.html`.
2. Make the change.
3. Change the date in the line "Last updated".
4. Make sure that the policy lists each API that the application uses.
5. Make sure that the policy lists each way that the application uses and stores data.
6. Do the procedure in section 4.1 to examine the page.
7. Commit the change.

### 4.4 Change the contact address

The contact address is in `privacy.html`, in the section "Contact".

1. Open `privacy.html`.
2. Replace the address in the "Contact" section.
3. Save the file.
4. Commit the change.

### 4.5 Revoke access for the application

Do this procedure to remove the access of the application to the YouTube account.

1. Go to `https://myaccount.google.com/permissions`.
2. Find Frontier AI Pipeline in the list.
3. Select the application.
4. Select **Remove access**.

> **NOTE**
> After you revoke access, the automated jobs cannot upload videos or read analytics.

## 5 Troubleshooting

| Symptom                              | Probable cause                              | Corrective action                                    |
|--------------------------------------|---------------------------------------------|------------------------------------------------------|
| A page shows no style                | The `<style>` element has an error.         | Examine the `<style>` element in the page head.      |
| Local server does not start          | Port 8000 is in use.                        | Use a different port, for example `8001`.            |
| A link does not open                 | The address in the `href` attribute is wrong.| Correct the address. Compare it with section 2.1.   |
| The text has strange characters      | The file is not in UTF-8 encoding.          | Save the file in UTF-8 encoding.                     |

## 6 Writing rules for this document

This document follows these ASD-STE100 rules:

- Sentences in procedures have a maximum of 20 words.
- Other sentences have a maximum of 25 words.
- Each sentence gives one idea.
- Procedures use the imperative (command) form.
- Verbs are in the active voice.
- The text uses the simple present tense, simple past tense, or future tense only.
- The text uses the same word for the same thing. For example, "page" always means one HTML file.
- Warnings and notes come before or after the applicable step. Warnings tell the user about a risk of harm or loss. Notes give extra information.

## 7 Glossary

| Term              | Meaning                                                                     |
|-------------------|-----------------------------------------------------------------------------|
| Operator          | The one YouTube creator who owns and uses the application.                  |
| Private draft     | A video on YouTube that only the channel owner can see until they publish it.|
| OAuth             | A method that lets an application access an account without a password.    |
| Audience retention| A report that shows how much of a video viewers watch.                      |
| STE               | Simplified Technical English (ASD-STE100).                                  |
