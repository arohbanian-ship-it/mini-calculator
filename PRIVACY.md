# Privacy

Mini Calculator works entirely on the local computer. It has no analytics, advertising, accounts, telemetry, or network communication.

The program saves these items in a local `calculator_state.txt` file so the next launch can restore the working session:

- window size and position;
- font size and digit precision;
- formatting, separator, keypad, and List Mode preferences;
- the last result;
- the calculator text and history.

The public source and downloadable release packages do not include any user's state file. Delete your local `calculator_state.txt` while the calculator is closed if you want to reset the saved session.
