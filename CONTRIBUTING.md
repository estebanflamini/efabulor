#Ways to contribute to this project:

- Test the program and report any issues/bugs.

- Suggest and/or implement new functionalities.

- Check the manual for mistakes.

- Translate the user interface. You will need to know how to use the gettext localisation system, or team with 
  someone who can provide you with the necessary gettext files. I cannot provide you with instructions on how to 
  use gettext.

- Provide a graphical interface. I opted not to write one myself yet because I had little time, and anyway, I feel 
much more comfortable working at the command line than in a point-and-click environment. Nonetheless, I always 
assumed the program will need a GUI at some point. That's why I provided the option to run the program in 
a 'scripted' mode, in which efabulor can be driven by an external program (instead of responding to user's 
keypresses). If you learn how to use efabulor in scripted mode, it should very easy to write an external program 
acting as a GUI for efabulor.

- Improve installation instructions. For the time being, installing espeak and all its required dependencies is to 
be done manually, and the instructions I provide in the manual are very limited. You can help me provide the users 
with better instructions. Alternatively...

- Help me develop a proper multiplatform installation script.

- Extend the program to enable using speech engines other than espeak, for the sake of users willing or 
constrained to do so.

- Help improve the program's design. I wrote this program over several years in my spare time, while I was 
learning to program in Python 2 first, and then in Python 3. (It was my first big project in Python.) Some design 
choices might be seen as objectionable or un-Pythonic.

  - Particularly, I chose to organize the main program (efabulor) in just one file, with the code structured in 
  static (non-instantiable) classes for the sake of encapsulation and readability. I believe the concept of static 
  class is objected by some Pythonists; as I first learned OOP with Java, they are a natural design choice for me. 
  If you think the code would be improved by converting static classes into regular ones (or by dividing the code 
  into several files organized as a package), that's a potential line of contribution, and it should not be a 
  difficult thing to do.

  - Besides the static classes, I think the program's design offers room for improvement. I tried several designs 
  and finally converged to a rather satisfactory one (it might still be flawed, but elegantly so :) by which I mean 
  that it should be rather easy to maintain and/or refactor incrementally without much code rewriting).

