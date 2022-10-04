from machine import Pin
import rp2
import utime
import json

# Record the current state of each light
# Also flag events we will need to process.
class LightState:
    # Actions are bits in a byte, so we can copy and modify quickly
    ON =   0b00000001
    OFF =  0b00000010
    DIMM = 0b00000100
    # Increment or Decrement by DIMM_INC, every 1/16th second
    DIMM_INC = 4

    def __init__(self, light_name, sm_index, pin_in, pin_out):
        # Remember the light settings
        self.level = 255             # Full on
        self.dimm = True             # So we must be dimming, not brightening
        self.light_was_on = False    # Assume the light was off. Recorded on switch up, so final state
        self.light_name = light_name # A label for the light

        self.irq_counter = 0         # Statemachine interrupts seen, this switch push (1/16th sec)
        # Use bits in a Integer to flag an event has occurred
        self.events = 0

        # Remember the arguments for debugging
        self.sm_index = sm_index
        self.pin_in = pin_in
        self.pin_out = pin_out

        self.switch_pin = Pin(pin_in, Pin.IN, Pin.PULL_UP)  # Pin from the switch
        self.light_pin = Pin(pin_out, Pin.OUT)              # Pin to indicate the light is on/off
        # Create a statemachine, using switch_sm() PIO ASM.
        # Statemachine clock is set to 2048Hz, and sm pin0 is pin_in
        self.sm = rp2.StateMachine(sm_index, switch_sm, freq=2048, in_base=self.switch_pin)
        # Statemachine interrupts are handled by irq_handler, passing the Statemachine and Pin_number
        self.sm.irq(handler=lambda ih: irq_handler(self.sm, sm_index, self))

    # Start the state machine monitoring this pin_in
    def sm_active(self):
        self.sm.active(1)

    # Set an action to be processed.
    # Done in the interrupt handler. Not here
    def set_event(self,v):
        self.events |= v

    # Copies, then zeros the event bitmap.
    # Returns the copy
    def get_events(self):
        #machine.disable_irq() #Pico locking up
        evs = self.events
        self.events = 0
        #machine.enable_irq()
        return evs

    # We can't actually dimm the lights, or turn them on/off,
    # so we just print out what we should be doing.
    def process_event(self):
        current_events = self.get_events()
        if (current_events & LightState.ON):
            print("light: {} On LVL {}".format(self.light_name, self.level))
        elif (current_events & LightState.OFF):
            print("light: {} Off".format(self.light_name))

        # Can only DIMM if the light is on
        if (current_events & LightState.DIMM) and self.light_pin.value() == 1:
            ms = utime.ticks_ms() % 1000
            if self.dimm :
                if self.level - LightState.DIMM_INC > 0: # Don't go negative
                    self.level -= LightState.DIMM_INC
                    print("{} light: {} LVL: {}".format(ms, self.light_name,self.level))
            else:
                if self.level + LightState.DIMM_INC < 255: # Don't go above full
                    self.level += LightState.DIMM_INC
                    print("{} light: {} LVL: {}".format(ms, self.light_name,self.level))


# switch_sm is PIO statemachine assembler.
@rp2.asm_pio() # Mark start of PIO ASM code block
def switch_sm():
  jmp('entry')            # Skip 'switch off' interrupt notification
  label('wait_pin_up')
  irq(block, rel(0))      # IRQ when switch is off again
  label('entry')
  wait(0, pin, 0)         # Wait for pin to be earthed (switch on)
  wrap_target()           # Loop sending interrupt every 128 cycles (1/16th s)
  irq(block, rel(0)) [31] # Send interrupt and wait for it to be picked up. Delay of 32 Clock cycles
  nop() [31]              # Delay 32 Clock cycles
  nop() [31]              # Delay 32 Clock cycles
  nop() [30]              # Delay 31 Clock cycles
  jmp(pin, 'wait_pin_up') # Stop IRQs if switch released. Takes 1 Clock cycle
  wrap()                  # Loop, sending IRQs

# Got IRQ every 128 Cycles (1/16th Second),
# Minimise time spent in this handler!
# We do turn on/off the light pin, but don't do the dimming here
# We just set an ON, OFF or DIMM event, for the main loop to handle.
def irq_handler(sm, sm_index,l):
    global lights
    global scope
    #print(l.sm_index, l.pin_in, l.pin_out, l.light_pin.value)
    sm.irq(handler=None) # Disable interrupts while in handler.
    #l = lights[sm_index]

    if l.switch_pin.value() == 0:  # Switch is down
        if l.light_pin.value() == 0:   # Light is off
            if l.irq_counter == 2:     # Debounce: Switch has been down for at least a 1/8th second
                l.light_pin.value(1)     # Turn on the light immediately
                l.events |= LightState.ON       # Notify a change has occurred
        elif l.irq_counter > 16:     # The switch has been down for more than a 1/2s
            l.events |= LightState.DIMM
        l.irq_counter += 1           # Inc interrupt counter, which means another 1/16s
    else :                          # Switch is now up, so we do exit processing
        if l.irq_counter <= 16:        # Switch was on for less than 1/2s, and is now up
            if l.light_was_on:         # State on last switch up was ON, so we are now turning off.
                l.light_pin.value(0)     # Turn off the light
                l.events |= LightState.OFF      # Notify that a change has occurred
        else:                      # Switch on > 1/2s, so we have been in dimm mode
            l.dimm = not l.dimm      # Reverse dimm direction, for next time
        l.light_was_on = l.light_pin.value() == 1    # Remember the final on/off state
        l.irq_counter = 0             # Switch is up, so we can reset the irq counter to 0

    sm.irq(handler=lambda ih: irq_handler(sm, sm_index,l)) # Enable interrupts again

# Change Lights in real world.
# This cycles through the lights[], checking for events turned on in the irq_handler.
def process_events():
    global lights
    # Start the statemachines
    for l in lights:
        l.sm_active()

    count = 0
    # We poll, as we only have 1 core, and no premption available.
    while True:
        for l in lights:
            l.process_event()
        count += 1
        utime.sleep(0.01) # Gives us lots of time to poll, and still take action for all lights

        # Debugging code. Printing out the second and state.
        # This can be removed
        if count % 100 == 0:
            print(count//100)
            print_state()

# Print out the state of each light
def print_state():
    global lights
    r = {}
    # i is the Lights[] index
    # l is lights[i]
    for i,l in enumerate(lights):
        r[i] = { "light": light_name, "index": i, "light_gpio": l.pin_out, "on": l.light_pin.value(), "level": l.level, "dimm": l.dimm }
    print( json.dumps(r) )


# Turn on/off a light, using the statemachine number as the index
def toggle_switch(s):
    global lights
    lights[s].light_pin.toggle()
    light_name, sm_index, pin_in, pin_out

# Set up each light switch pin_in, and light pin_out
# And assign a statemachine to monitor the pin_in
lights =  [ # Indexed by statemachine number
    LightState(light_name="light 0", sm_index=0, pin_in=0, pin_out=8),
    LightState(light_name="light 1", sm_index=1, pin_in=1, pin_out=9),
    LightState(light_name="light 2", sm_index=2, pin_in=2, pin_out=10),
    LightState(light_name="light 3", sm_index=3, pin_in=3, pin_out=11),
    LightState(light_name="light 4", sm_index=4, pin_in=4, pin_out=12),
    LightState(light_name="light 5", sm_index=5, pin_in=5, pin_out=13),
    LightState(light_name="light 6", sm_index=6, pin_in=6, pin_out=14),
    LightState(light_name="light 7", sm_index=7, pin_in=7, pin_out=15)
]
# For debugging, print out the intitial states
print_state()

# Loop forever, processing switch events
process_events()
