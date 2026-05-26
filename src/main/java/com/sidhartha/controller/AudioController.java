package com.sidhartha.controller;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("api/v1/audio")
public class AudioController {

    @PostMapping("/enhance")
    public String receiveFile(@RequestParam("file")MultipartFile file){
        System.out.println("File Name : "+file.getOriginalFilename());
        System.out.println("FIle size: "+file.getSize());
        return "File received!";
    }
}
