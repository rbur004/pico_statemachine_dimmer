# pico_statemachine_dimmer

Test of setting up the Pi Pico's PIO state machines to drive LED light dimmers

# Light state
Each light has an associated instance of the LightState class
There is an array of 8 LightState instances, one per PIO state machine.

LightState records:
* The current dimmer level.
* If we are currently dimming or brightening
* Remembers the ON/OFF state from the last use of the switch, for next time the switch is used

# Switch Down Events
Events are recorded by setting bits in an Integer in each LightState record. The interrupt handler sets events. The main loop handles and clears events. There is currently no locking of the event Integer, so it is possible to lose a DIMM event. ON/OFF events are one off events, so shouldn't be lost.
* The light is turned ON, if it was off
* The light alternately dims or brightens, if the switch is held down for longer than 1/2s
* The light is turned OFF, if it was ON, and the switch was down less than 1/2s

# The PIO state machines
Each state machine monitors an input switch pin.
* On switch down (earthed), the state machine sends an interrupt
* If the switch stays down, an interrupt is sent every 1/16th of a second
* On switch up, the state machine sends a final interrupt

# The interrupt handler
Timing is done by incrementing a per state machine counter, each interrupt is sent by a state machine.
Interrupts will occur approximately every 1/16s, while the switch is down, so 8 interrupts represent 1/2s.

* If the light was off, the output light pin is turned on, after 2 interrupts (1/8th second)
** An ON event is set, for the main loop to handle
** the light pin is set to on
* If the switch is held down for more than 8 interrupts (1/2s)
** A DIMM event is set, for the main loop to handle
* If the switch is released within 8 interrupts (1/2s)
** If the light was ON when the switch was pushed, then  an OFF event is set, for the main loop to handle
** The light pin is set to off
** The interrupt timing counter is reset to 0
** The final ON/OFF state is recorded in the LightState

# The main loop
Each light's LightState is checked at approximately 1/100th of a second intervals, for ON, OFF or DIMM events set by the interrupt handler.

Currently, these events just print out what would be done. DIMM events do alter the LightState level, in increments of 4.
