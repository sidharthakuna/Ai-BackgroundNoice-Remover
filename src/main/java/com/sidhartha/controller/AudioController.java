package com.sidhartha.controller;

import com.sidhartha.service.NoiceRemovalService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("api/v1/audio")
public class AudioController {

    @Autowired
    NoiceRemovalService noiceRemovalService; //spring give this from the service class
    @PostMapping("/enhance")
    public ResponseEntity<byte[]> receiveFile(@RequestParam("file") MultipartFile file) throws Exception {
        //===========
        //for api call
//        String uuid = noiceRemovalService.createProduction(file);
//        noiceRemovalService.startProduction(uuid);
//        String downloadUrl = noiceRemovalService.pollUntilDone(uuid);
//        byte[] cleanedAudio = noiceRemovalService.downloadFile(downloadUrl);
        //==============

        //for the "python" script "Ai"
        byte[] cleanedAudio = noiceRemovalService.removeNoise(file);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_OCTET_STREAM);
        headers.setContentDispositionFormData("attachment","enhanced_audio.wav");
        return ResponseEntity.ok()
                .headers(headers)
                .body(cleanedAudio);
    }

    @GetMapping("/test")
    public String testApi(){
        return noiceRemovalService.testApi(); //call the service method
    }

}
