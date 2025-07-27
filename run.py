from multiprocessing import Process
from app.scheduler import start_scheduler
from app import create_app

if __name__ == "__main__":
    # Start the scheduler in a separate process
    scheduler_process = Process(target=start_scheduler)
    scheduler_process.start()

    # Start Flask app
    app = create_app()
    app.run(host="0.0.0.0", port=8080)
