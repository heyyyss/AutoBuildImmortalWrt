/* N1: a display POST finishes before CarPlay has finished reconnecting. */
class N1DisplayGate {
  constructor({timeout = 30000, settle = 1200} = {}) {
    this.timeout = timeout;
    this.settle = settle;
    this.ticket = null;
  }
  begin(wasActive) {
    if (this.ticket) this.cancel(this.ticket);
    const ticket = {inactive: !wasActive, timer: null, settleTimer: null, finish: null, promise: null};
    ticket.promise = new Promise(resolve => {
      ticket.finish = () => {
        clearTimeout(ticket.timer);
        clearTimeout(ticket.settleTimer);
        if (this.ticket === ticket) this.ticket = null;
        resolve();
      };
    });
    this.ticket = ticket;
    ticket.timer = setTimeout(ticket.finish, this.timeout);
    return ticket;
  }
  session(message) {
    const t = this.ticket;
    if (!t || !["session", "hello"].includes(message.type)) return;
    if (!message.sessionActive) {
      t.inactive = true;
      clearTimeout(t.settleTimer);
    } else if (t.inactive) {
      clearTimeout(t.settleTimer);
      t.settleTimer = setTimeout(t.finish, this.settle);
    }
  }
  cancel(ticket) { if (ticket) ticket.finish(); }
  wait(ticket) { return ticket ? ticket.promise : Promise.resolve(); }
}
const n1DisplayGate = new N1DisplayGate();
