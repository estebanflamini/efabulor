# What is efabulor?

**efabulor** is a wrapper around **espeak**, a freely-available text-to-speech engine.

# What is it for?

Read an input text file, split it into sentences and send them to be read aloud one by one by **espeak**, with 
full keyboard control (moving between lines, stopping, pausing and resuming, finding text, etc.)

The splitting of sentences can be controlled by preprocessing the input text with transformation rules. (External 
preprocessing filters can also be used.) Substitution rules can be applied on a sentence-by-sentence basis to 
further control the reading.

# Which formats can it read?

**efabulor** reads plain-text files natively. Non plain-text files require an external conversion utility (such as 
**pandoc** or **unoconv**). Two companion scripts (**efabconv.py** and **efabucw.py**) are included to facilitate 
the conversion process.

# Does it have a GUI?

Currently **efabulor** is a command-line tool. Provisions for creating a GUI for future versions have been made, 
by providing a ‘scripted’ execution mode which would act as an API to the program. Any person interested in 
joining the development team (which currently has exactly one member) and help me create a GUI will be welcome and credited.

# How do I install it?

Instructions are given in the manual. For the time being installation is a manual process, consisting of copying 
the program files to a directory in your PATH and installing the required dependencies.

# What's new in version 2

Version 2 is a refactoring of Version 1, with an improved design, but no big changes to functionality. It is 
currently a beta version; it has been tested for a limited time, and only in Linux. It will be moved to non-beta 
state after more thorough testing in a production environment.

## What version should I use?

Whichever you want. If you try Version 2 and find any bugs, you can use Version 1 instead, as its functionality is 
basically the same (I'd appreciate if you report any issues so I can fix them).

Windows users: Version 2, unlike Version 1, has **not** been tested in Windows. However, the Windows-related code 
in both versions is the same, and it should work fine.
