/* Controlled fake of verified 15.3 methods only. Event integer is a test token,
   not an assertion of OpenTTD's numeric ET_ADMIN_PORT value. */
::events <- [];
::replies <- [];
::send_ok <- true;
::ticks <- 0;
class GSController {
    function Sleep(ticks) {
        if (ticks != 1) throw "unexpected script sleep";
        ::ticks++;
        if (::ticks == 2) throw "CONTROLLED_STOP";
    }
}
class GSEvent { static ET_ADMIN_PORT = 101; }
class ControlledAdminEvent {
    object = null;
    constructor(value) { this.object = value; }
    function GetEventType() { return GSEvent.ET_ADMIN_PORT; }
    function GetObject() { return this.object; }
}
class GSEventAdminPort {
    static function Convert(event) { return event; }
}
class GSEventController {
    static function IsEventWaiting() { return ::events.len() > 0; }
    static function GetNextEvent() { return ::events.remove(0); }
}
class GSAdmin {
    static function Send(value) { if (!::send_ok) return false; ::replies.append(value); return true; }
}

::markers <- [];
::marker_ticks <- [];
class GSLog {
    static function Info(value) { ::markers.append(value); ::marker_ticks.append(::ticks); }
}
